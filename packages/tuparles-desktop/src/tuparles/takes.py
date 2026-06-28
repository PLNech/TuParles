"""Dev-only raw-audio capture for replay (gated on ``TUPARLES_DEV``).

When the flag is set, every landed take's raw PCM is written next to its history
row (``takes/<id>.wav``) so it can be re-decoded across engines, settings and
seed regimes — "forensics before theory" turned into infra
(``scripts/replay_takes.py``). The synthetic-TTS code-switch eval proves a fix
survives *some* acoustics; real captured takes prove it survives *yours*.

This is your voice on disk, **unredacted** — unlike the stored transcript, which
strips block-tier PII (#115). So it is:

* OFF by default, behind a Réglages toggle (``dev_recording``) AND the
  ``TUPARLES_DEV`` env override (#8). The earlier env-only gate kept it from being
  "flippable by accident"; we keep that safety differently now — the toggle is
  off by default, carries an explicit raw-audio warning, and (the real guard)
  the tray shows a steady red dot the whole time it's armed, so it can never run
  silently. The env var stays as the override: set, it wins (truthy on / falsey
  off); unset, the setting decides.
* local-only (same XDG store as the history DB, never synced), and
* self-pruning: oldest takes are deleted once the directory passes a byte
  budget, so a dev convenience can never silently fill a disk.
"""

from __future__ import annotations

import os
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from tuparles import settings
from tuparles.history import db_path

SAMPLE_RATE = 16_000

# Bound the disk: int16 @ 16 kHz ≈ 32 KB/s, so 256 MB ≈ ~2 h of speech. Past
# this, the oldest takes yield (chosen retention: auto-rotate by cap).
_BYTES_BUDGET = 256 * 1024 * 1024
# Misses are rarer and individually small (a botched take is usually short), so
# a tighter budget — ~30 min — is plenty to keep the recent black holes around.
_MISS_BYTES_BUDGET = 64 * 1024 * 1024

_FALSEY = {"", "0", "false", "no", "off"}


def dev_recording_enabled() -> bool:
    """True iff dev raw-audio capture is on. ``TUPARLES_DEV``, when SET, is the
    override (truthy = on, falsey = off); when unset, the ``dev_recording``
    Réglages setting decides (default OFF). Raw *unredacted* voice on disk, so the
    default is off and the active state is always visible in the tray (#8)."""
    env = os.environ.get("TUPARLES_DEV")
    if env is not None:
        return env.strip().lower() not in _FALSEY
    return bool(settings.get("dev_recording"))


def takes_dir() -> Path:
    """Where take WAVs live: alongside the history DB, never in git."""
    return db_path().parent / "takes"


def misses_dir() -> Path:
    """Where *empty-decode* takes land — the "Rien entendu" black hole made
    visible (#10). A final decode that yields nothing records no history row and
    so no id-keyed WAV; without this the one failure you most want to debug is
    the one with zero trace. Dev-only, like every raw-audio capture."""
    return takes_dir() / "misses"


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


def save_miss(audio: np.ndarray, rate: int = SAMPLE_RATE) -> Path | None:
    """Write an empty-decode take to ``misses/miss-<ts>.wav`` and prune.

    Keyed by timestamp, not a history id (a miss has no row). No-op when dev
    capture is off or the audio is empty — same gate as ``save_take``.
    """
    if not dev_recording_enabled() or audio is None or audio.size == 0:
        return None
    directory = misses_dir()
    directory.mkdir(parents=True, exist_ok=True)
    # Microseconds in the name: two misses in the same second must not collide
    # (each one is evidence; overwriting loses a black hole).
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"miss-{stamp}.wav"
    pcm = np.ascontiguousarray(audio, dtype=np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    _prune(directory, _MISS_BYTES_BUDGET)
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
