#!/usr/bin/env python3
"""Replay captured dev takes across seed regimes and report drift.

Re-decodes every ``takes/<id>.wav`` (written when ``TUPARLES_DEV`` was set, see
``takes.py``) and diffs the result against the transcript stored for that id in
the history DB — the "drift vs stored transcript" reference. This is the
real-audio sibling of ``scripts/measure_seed_ablation.py``: that one runs on
synthetic TTS, this one on *your* voice. Needs the GPU box.

The stored transcript is PII-redacted (#115), so masked spans add a little WER
noise — fine for drift (a regression between engines/regimes shows as a *jump*,
not an absolute). Run::

    poetry run python scripts/replay_takes.py [--limit N]
"""

from __future__ import annotations

import argparse
import sqlite3
import wave
from contextlib import closing
from pathlib import Path

import numpy as np

from tuparles import engine, seed_prompt, takes
from tuparles.eval import wer
from tuparles.history import db_path
from tuparles.pipeline import postprocess

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only the newest N takes")
    args = ap.parse_args()

    wavs = sorted(takes.takes_dir().glob("*.wav"), key=lambda p: int(p.stem))
    if args.limit:
        wavs = wavs[-args.limit :]
    if not wavs:
        print(f"no takes in {takes.takes_dir()} — set TUPARLES_DEV=1 and dictate.")
        return

    transcripts = _stored_transcripts()
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


if __name__ == "__main__":
    main()
