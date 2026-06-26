"""The waveform amplitude mapping (audio.py _on_block → Recorder.level).

The old linear `rms / 8000` left quiet/mid speech as near-flat bars. The
perceptual map gates silence flat, pegs at a speech-typical RMS, and gamma-
lifts the middle so soft speech still visibly moves the bars.
"""

import numpy as np

from tuparles.audio import Recorder
from tuparles.config import LEVEL_FULL_SCALE, LEVEL_NOISE_FLOOR


def _level_at(rms_value: float) -> float:
    """Feed a constant-amplitude block (so RMS == |value|) through _on_block
    and read the resulting level. No PortAudio needed — _on_block is pure."""
    rec = Recorder()
    block = np.full((160, 1), int(rms_value), dtype=np.int16)
    rec._on_block(block, len(block), None, None)
    return rec.level


def test_silence_rests_flat():
    assert _level_at(0.0) == 0.0


def test_below_noise_floor_is_gated_to_zero():
    assert _level_at(LEVEL_NOISE_FLOOR - 20) == 0.0


def test_full_scale_pegs_the_meter():
    assert _level_at(LEVEL_FULL_SCALE) == 1.0


def test_above_full_scale_clamps():
    assert _level_at(LEVEL_FULL_SCALE * 2) == 1.0


def test_mid_speech_is_clearly_visible():
    # A speech RMS midway between the gate and full-scale must land well into
    # the visible range, not the near-flat the old linear rms/8000 map gave.
    # Calibration-relative so it survives a per-mic retune of the constants.
    mid = (LEVEL_NOISE_FLOOR + LEVEL_FULL_SCALE) / 2
    level = _level_at(mid)
    assert level > mid / 8000  # strictly more visible than the old linear map
    assert 0.3 < level < 0.8


def test_monotonic_in_loudness():
    span = LEVEL_FULL_SCALE - LEVEL_NOISE_FLOOR
    pts = [LEVEL_NOISE_FLOOR + span * f for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    levels = [_level_at(v) for v in pts]
    assert levels == sorted(levels)
