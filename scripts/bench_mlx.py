#!/usr/bin/env python3
"""Bench MLX Whisper sizes on synthetic EN / FR / code-switched clips.

Synthetic on purpose: the Mac has no recorded takes yet, and a TTS clip is a
floor, not a verdict. The question is which size keeps the blend tokens
("fan out", "ship", "pull request") and still decodes a short take faster
than it was spoken. Real dictated audio replaces this number later.

    poetry run python scripts/bench_mlx.py
    poetry run python scripts/bench_mlx.py --models mlx-community/whisper-large-v3-turbo

Writes docs/research/data/2026-10-28-mlx-bench.json. Clips stay in /tmp.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "research" / "data" / "2026-10-28-mlx-bench.json"

# One clip per register. The blend lines are the gate: an English token
# sitting where French phonetics wants to swallow it.
CLIPS = [
    ("en", "Ship this feature before Friday, the pull request is green."),
    ("fr", "Il faut livrer cette fonctionnalité avant vendredi, la requête est verte."),
    ("blend", "On disait fan out les agents, puis ship cette feature avant vendredi."),
    (
        "blend-hard",
        "Je review le pull request, le cache est chaud, et le déploiement part en staging.",
    ),
]

# Smallest first, so a slow large model is a choice made with the small
# numbers already on disk. large-v3-turbo is the CUDA rung's twin.
# Repo ids verified 2026-10-28. mlx-community names the small/medium
# conversions `*-mlx`; there is no `whisper-base`. The 5-bit turbo
# (whisper-large-v3-turbo-asr-5bit) downloads but its config carries
# `activation_dropout`, which mlx-whisper 0.4.3's ModelDimensions rejects,
# so it is not a candidate until the package catches up.
DEFAULT_MODELS = [
    "mlx-community/whisper-tiny",
    "mlx-community/whisper-small-mlx",
    "mlx-community/whisper-medium-mlx",
    "mlx-community/whisper-large-v3-turbo",
]


def say(voice: str, text: str, dest: Path) -> None:
    """macOS say → 16 kHz mono wav. Deterministic enough to compare models."""
    aiff = dest.with_suffix(".aiff")
    subprocess.run(
        ["say", "-v", voice, "-o", str(aiff), text], check=True, timeout=60
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
            "-ar", "16000", "-ac", "1", str(dest),
        ],
        check=True,
        timeout=60,
    )
    aiff.unlink(missing_ok=True)


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def voices() -> tuple[str, str]:
    """A French voice and an English voice, from whatever this macOS ships."""
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=30)
    names = [line.split()[0] for line in out.stdout.splitlines() if line.strip()]
    fr = next((n for n in names if n in ("Thomas", "Amelie", "Audrey")), names[0])
    en = next((n for n in names if n in ("Samantha", "Daniel", "Karen")), names[0])
    return fr, en


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    args = parser.parse_args()
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        print("say and ffmpeg are required", file=sys.stderr)
        return 1

    import mlx_whisper

    fr, en = voices()
    tmp = Path(tempfile.mkdtemp(prefix="tuparles-mlx-bench-"))
    clips = []
    for label, text in CLIPS:
        path = tmp / f"{label}.wav"
        # A French voice reading the English tokens is the realistic trap.
        say(fr if label != "en" else en, text, path)
        audio = load_wav(path)
        clips.append(
            {"label": label, "text": text, "seconds": round(audio.size / 16000, 2), "audio": audio}
        )
        print(f"clip {label}: {clips[-1]['seconds']}s", flush=True)

    rows = []
    for model in args.models:
        print(f"\n=== {model} ===", flush=True)
        # One silent call pays for the download and the compile. The timed
        # rows below are the warm decode, which is what a take actually costs.
        mlx_whisper.transcribe(
            np.zeros(16_000, dtype=np.float32),
            path_or_hf_repo=model,
            verbose=None,
            fp16=True,
            temperature=0.0,
        )
        for clip in clips:
            t0 = time.perf_counter()
            result = mlx_whisper.transcribe(
                clip["audio"],
                path_or_hf_repo=model,
                verbose=None,
                fp16=True,
                temperature=0.0,
                condition_on_previous_text=False,
            )
            elapsed = time.perf_counter() - t0
            text = (result.get("text") or "").strip()
            rtf = elapsed / clip["seconds"] if clip["seconds"] else None
            row = {
                "model": model,
                "clip": clip["label"],
                "seconds": clip["seconds"],
                "decode_s": round(elapsed, 3),
                "rtf": round(rtf, 3) if rtf is not None else None,
                "language": result.get("language"),
                "hypothesis": text,
                "reference": clip["text"],
            }
            rows.append(row)
            print(
                f"  {clip['label']:11} {elapsed:6.2f}s  rtf {rtf:.2f}  lang {row['language']}  {text}",
                flush=True,
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"voices": {"fr": fr, "en": en}, "rows": rows},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"\nwrote {OUT.relative_to(REPO)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
