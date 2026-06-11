"""Transcription via the vendored qwen-asr C binary.

Offline mode per the spike: weights are mmap'd so a fresh process per
utterance costs ~0.65 s — simpler and more robust than a long-lived child.
"""

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from tuparles.config import QWEN_BINARY, QWEN_MODEL_DIR, QWEN_THREADS, SAMPLE_RATE


def transcribe(audio: np.ndarray) -> str:
    """int16 mono 16 kHz samples → transcript text."""
    if audio.size == 0:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        _write_wav(Path(tmp.name), audio)
        result = subprocess.run(
            [
                str(QWEN_BINARY),
                "-d", str(QWEN_MODEL_DIR),
                "-i", tmp.name,
                "-t", str(QWEN_THREADS),
                "--silent",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if result.returncode != 0:
        raise RuntimeError(f"qwen_asr failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def _write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio.astype(np.int16).tobytes())
