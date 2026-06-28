"""Audible start cue: a soft tick the instant capture goes live.

Opt-in (settings "start_cue_sound", default off) — the visual cues (bubble
appearing, livelier bars, engine-coloured tray) are always on; this is the
extra "you can speak now" confirmation for those who want it.

Synthesized, not a shipped asset, and played through sounddevice — already a
dependency for capture, so no new deps and no sound-theme/codec assumptions.
Fire-and-forget and defensively silent: a cue must never delay or break a take.
"""

import numpy as np

from tuparles import settings

try:
    import sounddevice as sd
except (OSError, ImportError):  # no libportaudio (e.g. CI) — stay importable
    sd = None

_CUE_RATE = 44_100
_cue: np.ndarray | None = None  # built once, reused


def _tick() -> np.ndarray:
    """A short, gentle two-blip tick (~90 ms) with a fast decay — a polite
    'go', not a notification chime. Quiet on purpose (peak ~0.35)."""
    t = np.arange(int(_CUE_RATE * 0.09)) / _CUE_RATE
    env = np.exp(-t * 38.0)  # fast exponential decay
    tone = np.sin(2 * np.pi * 880.0 * t) + 0.5 * np.sin(2 * np.pi * 1320.0 * t)
    return (0.25 * env * tone).astype(np.float32)


def play_start() -> None:
    """Play the start cue if enabled. Non-blocking, never raises."""
    if sd is None or not settings.get("start_cue_sound"):
        return
    global _cue
    if _cue is None:
        _cue = _tick()
    try:
        sd.play(_cue, _CUE_RATE)  # non-blocking; uses the default output device
    except Exception:
        pass  # a missing/busy output device must never cost a take
