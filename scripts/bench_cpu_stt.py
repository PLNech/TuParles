#!/usr/bin/env python3
"""CPU STT bench — quality x speed across the realistic CPU rungs (#3).

We have a GPU eval (`tests/test_codeswitch_eval.py`, marked `gpu`); we had no
CPU number. This fills that gap: it runs the SAME adversarial code-switch corpus
the GPU eval uses, through the SAME user-facing path (engine decode ->
`pipeline.postprocess`), but on CPU under a realistic core budget — so a "pass"
means "what the user would have seen survives", not "the logits were fine".

Rungs benched today:
  * faster-whisper CPU (CTranslate2, int8): tiny / base / small / large-v3-turbo
  * qwen-asr (vendored C binary, the current CPU fallback)

The rung we CANNOT fill yet: whisper.cpp / GGML q5. pywhispercpp isn't installed
(that's task #4, WhisperCppEngine). So this run answers "how does the faster-
whisper CPU family compare to qwen, and which size is the sweet spot" — and #4's
job is to drop the whisper.cpp-q5 column into this same harness for the final
three-way call. The framing is deliberately honest: no faked q5 row.

Realistic core budget: launched under `taskset -c 0-5` (6 of 20 cores = 30%),
generous vs what a laptop on battery actually gives this app. Each engine is
also told cpu_threads=6 so it doesn't fight the affinity mask.

Assets live in the MAIN checkout (models/WAVs are gitignored, this is a
worktree) — we point at them by absolute path and never dirty the tree. The
faster-whisper model cache is global (~/.cache/huggingface), so the whisper
family needs no repo path at all.

Output: streams JSONL (one decode per line) so partial progress is readable
mid-run, then writes an aggregate JSON + a PNG chart at the end.

Run:
    taskset -c 0-5 poetry run python scripts/bench_cpu_stt.py --out /path/to/dir
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tuparles import eval as tp_eval
from tuparles.pipeline import postprocess

# The main checkout — gitignored assets (qwen binary/model, generated WAVs) live
# here, not in the worktree. Absolute paths, read-only: the worktree stays clean.
MAIN = Path("/home/pln/Work/Tools/TuParles")
WAV_DIR = MAIN / "tests" / "data" / "codeswitch" / "wav"
MANIFEST = WAV_DIR / "manifest.json"
CORPUS = MAIN / "tests" / "data" / "codeswitch" / "corpus.json"
QWEN_BINARY = MAIN / "vendor" / "qwen-asr" / "qwen_asr"
QWEN_MODEL_DIR = MAIN / "models" / "qwen3-asr-0.6b"

THREADS = 6  # match the taskset -c 0-5 affinity mask

# faster-whisper CPU rungs. int8 is the CPU-native CTranslate2 quant; GGML q5
# (whisper.cpp) is a different family and lands here via #4.
FW_MODELS = ["tiny", "base", "small", "large-v3-turbo"]


def read_wav_int16(path: Path) -> tuple[np.ndarray, float]:
    """16 kHz mono s16 WAV -> (int16 array, duration_s) — the mic path's shape."""
    with wave.open(str(path), "rb") as wav:
        assert wav.getframerate() == 16_000, f"{path.name}: not 16 kHz"
        assert wav.getnchannels() == 1, f"{path.name}: not mono"
        n = wav.getnframes()
        frames = wav.readframes(n)
    return np.frombuffer(frames, dtype=np.int16), n / 16_000.0


class FasterWhisperCpu:
    """faster-whisper on CPU, mirroring GpuEngine's final-decode options (beam=5,
    VAD, per-segment multilingual for code-switch) — minus the GPU batched
    pipeline (a GPU win; on CPU + short utterances it's a no-op at best) and minus
    initial_prompt (a constant bias across all engines; dropping it keeps the
    comparison about the model, and sidesteps desktop vocab/config in a worktree)."""

    def __init__(self, name: str) -> None:
        from faster_whisper import WhisperModel

        self.name = name
        self._model = WhisperModel(
            name, device="cpu", compute_type="int8", cpu_threads=THREADS
        )

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
        pcm = audio.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            pcm,
            beam_size=5,
            vad_filter=True,
            language=None,
            multilingual=True,  # FR+EN code-switch default: detect per segment
            word_timestamps=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


class QwenCpu:
    """Vendored qwen-asr C binary — the current CPU fallback. Mirrors
    QwenCpuEngine.transcribe (fresh process per utterance, --silent)."""

    name = "qwen-0.6b"

    def transcribe(self, audio: np.ndarray) -> str:
        import os
        import subprocess
        import tempfile

        if audio.size == 0:
            return ""
        fd, tmp_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with wave.open(str(tmp_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16_000)
                w.writeframes(audio.astype(np.int16).tobytes())
            result = subprocess.run(
                [
                    str(QWEN_BINARY),
                    "-d",
                    str(QWEN_MODEL_DIR),
                    "-i",
                    str(tmp_path),
                    "-t",
                    str(THREADS),
                    "--silent",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"qwen_asr failed: {result.stderr.strip()[:300]}")
        return result.stdout.strip()


@dataclass(frozen=True)
class EngineSpec:
    """One benchable engine. The local seed of the core engine registry (#14):
    a name, which gradient rung it serves, a lazy factory (never builds the heavy
    model at import — preserves the boundary), and an availability probe so GPU /
    embedded / not-yet-vendored rungs can sit in ONE registry and skip cleanly
    when their backend is absent. Adding the next engine = appending a spec."""

    key: str
    rung: str  # "cpu" | "gpu" | "embedded"
    build: Callable[[], object]  # () -> object with .transcribe(int16) -> str
    available: Callable[[], bool]


def _fw_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


# The registry. Future rungs live here as probe-gated specs — the "iterable
# benching suite" made literal: when #4 vendors pywhispercpp, its q5 row drops in
# beside qwen for the three-way call; the GPU rung joins the same table on the
# 4080 box. Until then their probes return False and they skip with a note.
REGISTRY: list[EngineSpec] = [
    *[
        EngineSpec(f"fw-{m}", "cpu", (lambda m=m: FasterWhisperCpu(m)), _fw_available)
        for m in FW_MODELS
    ],
    EngineSpec("qwen", "cpu", QwenCpu, QWEN_BINARY.exists),
    # FUTURE (#4): EngineSpec("whispercpp-q5", "cpu", WhisperCppEngine, _pwcpp_available)
    # FUTURE:      EngineSpec("fw-large-v3-turbo", "gpu", GpuEngine, _cuda_available)
]


def build_engines(only: list[str] | None) -> list[EngineSpec]:
    selected = [s for s in REGISTRY if not only or s.key in only]
    live, skipped = [], []
    for spec in selected:
        (live if spec.available() else skipped).append(spec)
    for spec in skipped:
        print(f"[bench] skip {spec.key} ({spec.rung}): backend unavailable", flush=True)
    return live


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def decode_one(
    engine, key: str, rung: str, entry: dict, audio, dur: float, case: dict
) -> dict:
    """One timed decode → postprocess → score, as a JSONL-ready row. A decode
    that throws is recorded (empty text, error string) rather than aborting the
    run — one bad WAV shouldn't cost the whole engine's numbers."""
    t0 = time.perf_counter()
    try:
        raw, err = engine.transcribe(audio), None
    except Exception as exc:
        raw, err = "", str(exc)[:200]
    elapsed = time.perf_counter() - t0
    text = postprocess(raw)
    res = tp_eval.score_case(case, text)
    return {
        "engine": key,
        "rung": rung,
        "file": entry["file"],
        "case_id": entry["case_id"],
        "voice": entry["voice"],
        "elapsed_s": round(elapsed, 3),
        "audio_s": round(dur, 3),
        "rtf": round(elapsed / dur, 3) if dur else None,
        "wer": round(res.wer, 3),
        "passed": res.passed,
        "missing": res.missing,
        "leaked": res.leaked,
        "hypothesis": text,
        "error": err,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output dir for jsonl/json/png")
    ap.add_argument("--only", nargs="*", help="subset of engine keys to run")
    ap.add_argument("--limit", type=int, default=0, help="cap #WAVs (smoke test)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jsonl = out / "cpu_bench.jsonl"
    summary_path = out / "cpu_bench_summary.json"
    png_path = out / "cpu_bench.png"

    cases = {c["id"]: c for c in json.loads(CORPUS.read_text())["cases"]}
    entries = json.loads(MANIFEST.read_text())["files"]
    if args.limit:
        entries = entries[: args.limit]

    engines = build_engines(args.only)
    print(
        f"[bench] {len(entries)} WAVs x {len(engines)} engines, threads={THREADS}",
        flush=True,
    )
    print(f"[bench] engines: {[s.key for s in engines]}", flush=True)

    # Preload audio once (shared across engines for identical inputs).
    audio_cache = {e["file"]: read_wav_int16(WAV_DIR / e["file"]) for e in entries}

    results: list[dict] = []
    with jsonl.open("w") as jf:
        for spec in engines:
            key = spec.key
            print(f"\n[bench] === {key} ({spec.rung}): loading ===", flush=True)
            t_load = time.perf_counter()
            engine = spec.build()
            load_s = time.perf_counter() - t_load
            print(f"[bench] {key} loaded in {load_s:.1f}s", flush=True)
            for i, entry in enumerate(entries, 1):
                audio, dur = audio_cache[entry["file"]]
                row = decode_one(
                    engine, key, spec.rung, entry, audio, dur, cases[entry["case_id"]]
                )
                results.append(row)
                jf.write(json.dumps(row) + "\n")
                jf.flush()
                if i % 12 == 0 or i == len(entries):
                    print(f"[bench] {key}: {i}/{len(entries)}", flush=True)

    # Aggregate per engine.
    summary = {}
    for spec in engines:
        key = spec.key
        rows = [r for r in results if r["engine"] == key]
        wers = [r["wer"] for r in rows]
        rtfs = [r["rtf"] for r in rows if r["rtf"] is not None]
        summary[key] = {
            "rung": spec.rung,
            "n": len(rows),
            "pass_rate": round(sum(r["passed"] for r in rows) / len(rows), 3),
            "mean_wer": round(statistics.mean(wers), 3),
            "median_wer": round(statistics.median(wers), 3),
            "mean_rtf": round(statistics.mean(rtfs), 3),
            "p90_rtf": round(percentile(rtfs, 0.90), 3),
            "errors": sum(1 for r in rows if r["error"]),
        }
    summary_path.write_text(json.dumps(summary, indent=2))
    print("\n[bench] === SUMMARY ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)

    _plot(summary, png_path)
    print(
        f"\n[bench] wrote {jsonl}\n[bench] wrote {summary_path}\n"
        f"[bench] wrote {png_path}",
        flush=True,
    )


def _plot(summary: dict, png_path: Path) -> None:
    """Quality (pass-rate / WER) x speed (RTF) scatter — the tradeoff at a glance.
    The sweet spot is top-left: high pass-rate, low RTF (faster than realtime)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"[bench] matplotlib unavailable, skipping PNG: {exc}", flush=True)
        return

    keys = list(summary)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    rtfs = [summary[k]["mean_rtf"] for k in keys]
    passes = [summary[k]["pass_rate"] * 100 for k in keys]
    wers = [summary[k]["mean_wer"] for k in keys]

    ax1.scatter(rtfs, passes, s=120)
    for k, x, y in zip(keys, rtfs, passes, strict=False):
        ax1.annotate(k, (x, y), textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax1.axvline(1.0, ls="--", color="grey", lw=1)
    ax1.text(
        1.02,
        ax1.get_ylim()[0],
        "1x realtime",
        color="grey",
        fontsize=8,
        rotation=90,
        va="bottom",
    )
    ax1.set_xlabel("mean RTF  (lower = faster; <1 = faster than realtime)")
    ax1.set_ylabel("code-switch pass-rate  (%)")
    ax1.set_title("Quality vs speed — sweet spot is top-left")
    ax1.grid(alpha=0.3)

    xs = range(len(keys))
    ax2.bar(xs, wers)
    ax2.set_xticks(list(xs))
    ax2.set_xticklabels(keys, rotation=30, ha="right", fontsize=9)
    ax2.set_ylabel("mean WER  (lower = better)")
    ax2.set_title("Word error rate by rung")
    ax2.grid(alpha=0.3, axis="y")

    fig.suptitle(
        "TuParles CPU STT bench (6 cores / 30%) — code-switch corpus", fontsize=12
    )
    fig.tight_layout()
    fig.savefig(png_path, dpi=110)
    print(f"[bench] chart -> {png_path}", flush=True)


if __name__ == "__main__":
    main()
