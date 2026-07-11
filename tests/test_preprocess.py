import numpy as np

from tuparles.config import (
    NORMALIZE_MAX_GAIN,
    NORMALIZE_SILENCE_FLOOR,
    NORMALIZE_TARGET_PEAK,
    SAMPLE_RATE,
)
from tuparles.preprocess import normalize_audio, prepare_pcm, to_int16, trim_silence


def _tone(seconds: float, amp: int = 8000, freq: float = 440.0) -> np.ndarray:
    """A speech-stand-in tone burst as int16 (loud enough to clear the RMS gate)."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.int16)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16)


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


class TestPreparePcm:
    """The shared decode-prep seam (#131): int16→float32 + normalize, and the
    float32 passthrough the offline ffmpeg path relies on."""

    def test_int16_converted_and_normalized(self):
        buf = _tone(1.0, amp=3000)  # ~0.09 of full scale → boosted to target
        out = prepare_pcm(buf)
        assert out.dtype == np.float32
        assert np.isclose(np.abs(out).max(), NORMALIZE_TARGET_PEAK, atol=1e-2)

    def test_float32_passthrough_normalized(self):
        buf = (np.sin(np.linspace(0, 50, 16000)) * 0.1).astype(np.float32)
        out = prepare_pcm(buf)
        assert out.dtype == np.float32
        assert np.isclose(np.abs(out).max(), NORMALIZE_TARGET_PEAK, atol=1e-2)

    def test_to_int16_roundtrip(self):
        f = (np.sin(np.linspace(0, 50, 1000)) * 0.95).astype(np.float32)
        i = to_int16(f)
        assert i.dtype == np.int16
        assert abs(int(np.abs(i).max()) - int(0.95 * 32767)) < 50

    def test_to_int16_clips_out_of_range(self):
        i = to_int16(np.array([2.0, -2.0, 0.0], dtype=np.float32))
        assert i.max() <= 32767
        assert i.min() >= -32767


class TestTrimSilence:
    """Lead/tail silence trim (#131). silero-vad isn't installed in CI, so these
    exercise the deterministic RMS fallback tier + the safety interlocks."""

    def test_empty_returns_empty(self):
        assert trim_silence(np.zeros(0, dtype=np.int16)).size == 0

    def test_trailing_silence_trimmed(self):
        buf = np.concatenate([_tone(2.0), _silence(10.0)])
        out = trim_silence(buf)
        assert out.size < buf.size
        assert out.size >= int(2.0 * SAMPLE_RATE)  # never eats into speech
        assert out.size <= int(2.6 * SAMPLE_RATE)  # kept ~0.4s tail margin, not 10s

    def test_leading_silence_trimmed(self):
        buf = np.concatenate([_silence(5.0), _tone(2.0)])
        out = trim_silence(buf)
        assert out.size < buf.size
        assert out.size <= int(2.6 * SAMPLE_RATE)

    def test_pure_silence_returned_unchanged(self):
        buf = _silence(5.0)
        out = trim_silence(buf)
        assert np.array_equal(out, buf)  # no speech → hand back the buffer

    def test_soft_onset_speech_not_over_trimmed(self):
        n = int(3.0 * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        ramp = np.linspace(0.05, 1.0, n)  # amplitude ramps up: a soft onset
        buf = (np.sin(2 * np.pi * 440 * t) * ramp * 8000).astype(np.int16)
        out = trim_silence(buf)
        assert out.size >= int(2.5 * SAMPLE_RATE)  # the bulk of the ramp survives

    def test_short_clip_returned_unchanged(self):
        buf = _tone(0.3)  # under TRIM_MIN_RESULT_S
        out = trim_silence(buf)
        assert np.array_equal(out, buf)  # never hand an engine <1.25s

    def test_trim_below_min_result_floor_kept(self, monkeypatch):
        # Real-take A/B regression (floor 0.5 → 1.25 s): a short speech span whose
        # trimmed+padded result would land under TRIM_MIN_RESULT_S must hand back the
        # ORIGINAL buffer — whisper is unreliable on sub-~1 s clips, so when the trim
        # would starve it we keep the audio (the asymmetric-safety house bias). Under
        # the old 0.5 s floor this ~0.7 s span (→ ~1.1 s padded) WOULD have trimmed.
        import tuparles.preprocess as pp

        monkeypatch.setattr(pp, "_silero_unavailable", True)  # force the RMS tier
        buf = np.concatenate([_tone(0.7), _silence(3.0)])
        out = pp.trim_silence(buf)
        assert np.array_equal(out, buf)

    def test_over_trim_guard_keeps_original(self):
        # 30s buffer, a 0.1s blip: a valid trim would leave <5% → distrust, keep.
        buf = np.concatenate([_silence(10.0), _tone(0.1), _silence(20.0)])
        out = trim_silence(buf)
        assert np.array_equal(out, buf)

    def test_dtype_preserved_int16(self):
        buf = np.concatenate([_tone(2.0), _silence(5.0)])
        assert trim_silence(buf).dtype == np.int16

    def test_dtype_preserved_float32(self):
        speech = (np.sin(np.linspace(0, 400, 2 * SAMPLE_RATE)) * 0.5).astype(np.float32)
        buf = np.concatenate([speech, np.zeros(5 * SAMPLE_RATE, dtype=np.float32)])
        out = trim_silence(buf)
        assert out.dtype == np.float32
        assert out.size < buf.size

    def test_never_raises_returns_input_on_error(self, monkeypatch):
        import tuparles.preprocess as pp

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(pp, "_silero_unavailable", True)
        monkeypatch.setattr(pp, "_rms_speech_span", _boom)
        buf = np.concatenate([_tone(2.0), _silence(3.0)])
        assert np.array_equal(pp.trim_silence(buf), buf)  # error → input unchanged

    def test_silero_failure_falls_back_to_rms(self, monkeypatch):
        import tuparles.preprocess as pp

        def _no_silero(*_a, **_k):
            raise ImportError("no silero-vad")

        monkeypatch.setattr(pp, "_silero_unavailable", False)
        monkeypatch.setattr(pp, "_silero_speech_span", _no_silero)
        buf = np.concatenate([_tone(2.0), _silence(10.0)])
        out = pp.trim_silence(buf)
        assert out.size < buf.size  # RMS fallback still trimmed the tail
        assert pp._silero_unavailable is True  # switched to RMS permanently
