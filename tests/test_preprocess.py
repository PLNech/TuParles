import numpy as np

from tuparles.config import (
    NORMALIZE_MAX_GAIN,
    NORMALIZE_SILENCE_FLOOR,
    NORMALIZE_TARGET_PEAK,
)
from tuparles.preprocess import normalize_audio


class TestNormalize:
    def test_empty_in_empty_out(self):
        out = normalize_audio(np.zeros(0, dtype=np.float32))
        assert out.size == 0

    def test_quiet_speech_boosted_toward_target(self):
        # 0.1 peak needs ~9.5x gain — under the cap, so it reaches target.
        quiet = (np.sin(np.linspace(0, 50, 16000)) * 0.1).astype(np.float32)
        out = normalize_audio(quiet)
        assert np.isclose(np.abs(out).max(), NORMALIZE_TARGET_PEAK, atol=1e-2)

    def test_loud_audio_is_near_noop_and_never_clips(self):
        loud = (np.sin(np.linspace(0, 50, 16000)) * 0.9).astype(np.float32)
        out = normalize_audio(loud)
        assert np.abs(out).max() <= 1.0  # never clips
        # gain ≈ 0.95/0.9 ≈ 1.05 — barely touched
        assert np.isclose(np.abs(out).max(), NORMALIZE_TARGET_PEAK, atol=1e-3)

    def test_output_stays_float32(self):
        out = normalize_audio(np.full(100, 0.3, dtype=np.float32))
        assert out.dtype == np.float32

    def test_silence_left_untouched(self):
        hiss = (np.random.RandomState(0).randn(16000) * 1e-4).astype(np.float32)
        peak_before = np.abs(hiss - hiss.mean()).max()
        assert peak_before < NORMALIZE_SILENCE_FLOOR  # precondition
        out = normalize_audio(hiss)
        # not amplified toward target — gain of 1 (only DC removed)
        assert np.abs(out).max() < NORMALIZE_SILENCE_FLOOR

    def test_max_gain_cap_respected(self):
        # Whisper-quiet: peak so low that uncapped gain would exceed the cap.
        tiny_peak = NORMALIZE_TARGET_PEAK / (NORMALIZE_MAX_GAIN * 4)
        sig = (np.sin(np.linspace(0, 50, 16000)) * tiny_peak).astype(np.float32)
        out = normalize_audio(sig)
        applied = np.abs(out).max() / tiny_peak
        assert applied <= NORMALIZE_MAX_GAIN + 0.1  # float32 slack

    def test_dc_offset_removed(self):
        biased = (np.sin(np.linspace(0, 50, 16000)) * 0.3 + 0.4).astype(np.float32)
        out = normalize_audio(biased)
        assert abs(float(out.mean())) < 1e-3
