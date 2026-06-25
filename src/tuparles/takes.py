"""Dev-only raw-audio capture for replay (gated on ``TUPARLES_DEV``).

When the flag is set, every landed take's raw PCM is written next to its history
row (``takes/<id>.wav``) so it can be re-decoded across engines, settings and
seed regimes — "forensics before theory" turned into infra
(``scripts/replay_takes.py``). The synthetic-TTS code-switch eval proves a fix
survives *some* acoustics; real captured takes prove it survives *yours*.

This is your voice on disk, **unredacted** — unlike the stored transcript, which
strips block-tier PII (#115). So it is:

* OFF unless ``TUPARLES_DEV`` is truthy — chosen over a Réglages toggle on
  purpose: raw voice on disk must not be flippable by accident.
* local-only (same XDG store as the history DB, never synced), and
* self-pruning: oldest takes are deleted once the directory passes a byte
  budget, so a dev convenience can never silently fill a disk.
"""

from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np

from tuparles.history import db_path

SAMPLE_RATE = 16_000

# Bound the disk: int16 @ 16 kHz ≈ 32 KB/s, so 256 MB ≈ ~2 h of speech. Past
# this, the oldest takes yield (chosen retention: auto-rotate by cap).
_BYTES_BUDGET = 256 * 1024 * 1024

_FALSEY = {"", "0", "false", "no", "off"}


def dev_recording_enabled() -> bool:
    """True iff ``TUPARLES_DEV`` is set to a truthy value — the only gate."""
    return os.environ.get("TUPARLES_DEV", "").strip().lower() not in _FALSEY


def takes_dir() -> Path:
    """Where take WAVs live: alongside the history DB, never in git."""
    return db_path().parent / "takes"


def save_take(take_id: int, audio: np.ndarray, rate: int = SAMPLE_RATE) -> Path | None:
    """Write ``<take_id>.wav`` (mono s16) and prune. No-op when disabled/empty.

    Keyed by the history row id so replay can pair audio ↔ stored transcript.
    """
    if not dev_recording_enabled() or audio is None or audio.size == 0:
        return None
    directory = takes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{take_id}.wav"
    pcm = np.ascontiguousarray(audio, dtype=np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    _prune(directory)
    return path


def _prune(directory: Path, budget: int | None = None) -> None:
    """Delete oldest WAVs until the directory is under ``budget`` bytes.

    Budget resolved at call time (not as a default arg) so it stays tunable.
    """
    if budget is None:
        budget = _BYTES_BUDGET
    wavs = sorted(directory.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in wavs)
    while wavs and total > budget:
        victim = wavs.pop(0)
        total -= victim.stat().st_size
        victim.unlink(missing_ok=True)
