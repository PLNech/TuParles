#!/usr/bin/env python3
"""Replay captured dev takes across seed regimes and report drift.

Re-decodes every ``takes/<id>.wav`` (written when ``TUPARLES_DEV`` was set, see
``takes.py``) and diffs the result against the transcript stored for that id in
the history DB — the "drift vs stored transcript" reference. This is the
real-audio sibling of ``scripts/measure_seed_ablation.py``: that one runs on
synthetic TTS, this one on *your* voice.

Two engines (#10): ``--engine gpu`` (default) sweeps the seed regimes through
large-v3-turbo and needs the GPU box; ``--engine cpu`` runs the vendored qwen
binary, so the drift harness works with the card wedged — through the engine
that actually serves you on a no-GPU day. qwen takes no initial_prompt, so the
CPU path ignores the seed regimes and just does one decode per take.

The stored transcript is PII-redacted (#115), so masked spans add a little WER
noise — fine for drift (a regression between engines/regimes shows as a *jump*,
not an absolute).

``--trim`` (#131) is the silence-trim A/B: it decodes each take raw vs trimmed
and reports ΔWER + Δdecode_s + trimmed-seconds, NUMBERS ONLY (no transcript, no
content). It replays only takes the user consented to share (share_ok=1, the
``review_takes.py`` gate), and — per the no-GPU-on-battery house rule — drops to
a CPU-only A/B when off mains, saying so. Run::

    poetry run python scripts/replay_takes.py [--engine gpu|cpu] [--limit N]
    poetry run python scripts/replay_takes.py --trim [--engine gpu|cpu]
"""

from __future__ import annotations

import argparse
import glob
import shutil
import sqlite3
import statistics
import subprocess
import time
import wave
from contextlib import closing
from pathlib import Path

import numpy as np

from tuparles import engine, history, seed_prompt, takes
from tuparles.config import SAMPLE_RATE
from tuparles.eval import wer
from tuparles.history import db_path
from tuparles.pipeline import postprocess
from tuparles.preprocess import trim_silence

# A regime is just an initial_prompt builder; swapping engines is a one-line
# extension (build a QwenCpuEngine and add a column). Settings first, per the
# 2026-06-25 work that motivated this.
REGIMES = {
    "OFF": lambda: None,
    "CURATED": lambda: seed_prompt.initial_prompt(seeds=[], bias_enabled=True),
    "FULL": lambda: seed_prompt.initial_prompt(),
}


def _stored_transcripts() -> dict[int, str]:
    with closing(sqlite3.connect(db_path())) as conn:
        return {
            row[0]: row[1] for row in conn.execute("SELECT id, text FROM dictations")
        }


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def _replay_gpu(wavs, transcripts) -> None:
    eng = engine.GpuEngine()
    drift: dict[str, list[float]] = {r: [] for r in REGIMES}
    for path in wavs:
        take_id = int(path.stem)
        ref = transcripts.get(take_id)
        if not ref:
            continue  # take with no surviving history row; skip
        audio = _read_wav(path)
        print(f"\n• take {take_id}  (ref: {ref[:70]!r})")
        for regime, prompt_fn in REGIMES.items():
            engine._vocab_prompt = prompt_fn  # type: ignore[assignment]
            heard = postprocess(eng.transcribe(audio).text)
            d = wer(ref, heard)
            drift[regime].append(d)
            print(f"  {regime:8} wer={d:.2f}  {heard[:70]!r}")

    print("\n===== mean drift vs stored transcript (lower = closer) =====")
    for regime, ds in drift.items():
        mean = sum(ds) / len(ds) if ds else float("nan")
        print(f"  {regime:8} {mean:.3f}  (n={len(ds)})")


def _replay_cpu(wavs, transcripts) -> None:
    """qwen-CPU, one decode per take (no seed regimes — qwen ignores prompts)."""
    eng = engine.QwenCpuEngine()
    drifts: list[float] = []
    for path in wavs:
        take_id = int(path.stem)
        ref = transcripts.get(take_id)
        if not ref:
            continue  # take with no surviving history row; skip
        audio = _read_wav(path)
        heard = postprocess(eng.transcribe(audio).text)
        d = wer(ref, heard)
        drifts.append(d)
        print(f"\n• take {take_id}  wer={d:.2f}")
        print(f"  ref:   {ref[:70]!r}")
        print(f"  heard: {heard[:70]!r}")

    mean = sum(drifts) / len(drifts) if drifts else float("nan")
    print("\n===== mean drift vs stored transcript (lower = closer) =====")
    print(f"  qwen-cpu {mean:.3f}  (n={len(drifts)})")


def _on_ac_power() -> bool:
    """True on mains power. House rule: no GPU decode on battery — real watts, and
    the user will reject it. Unknown state (a desktop with no battery node) is
    treated as mains. Best-effort; never raises."""
    if shutil.which("on_ac_power"):
        rc = subprocess.run(["on_ac_power"], capture_output=True).returncode
        if rc in (0, 1):  # 0 = on AC, 1 = on battery (255 = unknown → fall through)
            return rc == 0
    online = glob.glob("/sys/class/power_supply/A*/online")
    if online:
        try:
            return any(Path(p).read_text().strip() == "1" for p in online)
        except OSError:
            pass
    return True


def _replay_trim(wavs, transcripts, engine_name: str) -> None:
    """A/B the silence trim on real takes: decode raw vs trimmed, report per-take
    and aggregate ΔWER (vs stored transcript) + Δdecode_s + trimmed-seconds.

    NUMBERS ONLY — never a word of transcript, never a filename with content: the
    take id is an integer, WER/seconds are integers/floats. Safe to paste. Consent
    is a WHERE clause upstream (only share_ok=1 rows reach here), not a promise."""
    eng = engine.GpuEngine() if engine_name == "gpu" else engine.QwenCpuEngine()
    rows: list[tuple[int, float, float, float, float, float]] = []
    for path in wavs:
        take_id = int(path.stem)
        ref = transcripts.get(take_id)
        if not ref:
            continue  # not consented / no surviving row — skip
        audio = _read_wav(path)
        trimmed = trim_silence(audio)
        raw_dur = audio.size / SAMPLE_RATE
        trim_dur = trimmed.size / SAMPLE_RATE

        t0 = time.monotonic()
        raw_heard = postprocess(eng.transcribe(audio).text)
        raw_s = time.monotonic() - t0
        t1 = time.monotonic()
        trim_heard = postprocess(eng.transcribe(trimmed).text)
        trim_s = time.monotonic() - t1

        raw_wer = wer(ref, raw_heard)
        trim_wer = wer(ref, trim_heard)
        rows.append((take_id, raw_wer, trim_wer, raw_s, trim_s, raw_dur - trim_dur))
        print(
            f"take {take_id}: wer {raw_wer:.2f}→{trim_wer:.2f} "
            f"(Δ{trim_wer - raw_wer:+.2f})  decode {raw_s:.2f}→{trim_s:.2f}s "
            f"(Δ{trim_s - raw_s:+.2f})  trimmed {raw_dur - trim_dur:.1f}s"
        )
    _trim_summary(rows, engine_name)


def _trim_summary(rows, engine_name: str) -> None:
    print("\n===== trim A/B summary (numbers only) =====")
    if not rows:
        print(
            "  no consented takes to replay (share_ok=1). Grant some with "
            "`poetry run python scripts/review_takes.py`, then re-run."
        )
        return

    def _stats(xs) -> str:
        return (
            f"mean {statistics.mean(xs):+.3f}  median {statistics.median(xs):+.3f}"
            f"  min {min(xs):+.3f}  max {max(xs):+.3f}"
        )

    d_wer = [r[2] - r[1] for r in rows]
    d_dec = [r[4] - r[3] for r in rows]
    removed = [r[5] for r in rows]
    print(f"  engine={engine_name}  n={len(rows)}")
    print(f"  ΔWER (trim−raw, ≤0 = no harm):        {_stats(d_wer)}")
    print(f"  Δdecode_s (trim−raw, <0 = faster):    {_stats(d_dec)}")
    print(
        f"  trimmed seconds removed: mean {statistics.mean(removed):.2f}  "
        f"median {statistics.median(removed):.2f}  "
        f"min {min(removed):.2f}  max {max(removed):.2f}"
    )
    print("  (small n → wide error bars; read as direction, not a point estimate.)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--engine", choices=("gpu", "cpu"), default="gpu", help="decode backend"
    )
    ap.add_argument("--limit", type=int, default=None, help="only the newest N takes")
    ap.add_argument(
        "--trim",
        action="store_true",
        help="A/B the silence trim (raw vs trimmed) over CONSENTED takes; "
        "numbers only. On battery the GPU leg is skipped (CPU A/B only).",
    )
    args = ap.parse_args()

    if args.trim:
        engine_name = args.engine
        if engine_name == "gpu" and not _on_ac_power():
            print(
                "on battery — house rule forbids a GPU decode; running the CPU "
                "A/B only (the GPU leg is skipped, and this is why)."
            )
            engine_name = "cpu"
        # Consent gate: A/B only the takes the user explicitly flagged shareable
        # (share_ok=1). shared_rows() returns (id, ts, lang, text).
        consented = {row[0]: row[3] for row in history.shared_rows()}
        wavs = sorted(
            (p for p in takes.takes_dir().glob("*.wav") if int(p.stem) in consented),
            key=lambda p: int(p.stem),
        )
        if args.limit:
            wavs = wavs[-args.limit :]
        _replay_trim(wavs, consented, engine_name)
        return

    wavs = sorted(takes.takes_dir().glob("*.wav"), key=lambda p: int(p.stem))
    if args.limit:
        wavs = wavs[-args.limit :]
    if not wavs:
        print(f"no takes in {takes.takes_dir()} — set TUPARLES_DEV=1 and dictate.")
        return

    transcripts = _stored_transcripts()
    if args.engine == "cpu":
        _replay_cpu(wavs, transcripts)
    else:
        _replay_gpu(wavs, transcripts)


if __name__ == "__main__":
    main()
