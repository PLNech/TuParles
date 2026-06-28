"""Audio conditioning before STT.

Whisper is robust to noise by design (trained on messy, real-world audio),
so we deliberately do NOT denoise: spectral subtraction / RNNoise add
artifacts, latency, and a dependency, and over-cleaning measurably hurts the
decode. Its VAD already drops silence.

What quiet speech actually lacks is *level* — a soft take uses only a sliver
of the int16 range, so the effective SNR after the /32768 scaling is poor.
Peak normalization is the safe win: a no-op on already-loud audio (gain ≈ 1,
never clips) and a real boost on quiet audio. DC-offset removal fixes mics
with a bias. Both are pure, single-pass, dependency-free.
"""

import numpy as np

from tuparles.config import (
    NORMALIZE_MAX_GAIN,
    NORMALIZE_SILENCE_FLOOR,
    NORMALIZE_TARGET_PEAK,
)


def normalize_audio(pcm: np.ndarray) -> np.ndarray:
    """float32 PCM in [-1, 1] → DC-removed, peak-normalized float32.

    Peak (not RMS) normalization so the gain can never push a sample past
    full scale — no clipping, ever. The gain is capped so a near-silent
    buffer isn't blown up into pure noise, and a silence floor leaves true
    silence untouched (amplifying it would only raise the hiss).
    """
    if pcm.size == 0:
        return pcm
    pcm = (pcm - np.float32(pcm.mean())).astype(np.float32)  # DC offset
    peak = float(np.abs(pcm).max())
    if peak < NORMALIZE_SILENCE_FLOOR:
        return pcm
    gain = min(NORMALIZE_TARGET_PEAK / peak, NORMALIZE_MAX_GAIN)
    return (pcm * np.float32(gain)).astype(np.float32)
