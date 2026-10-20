"""Far-field gain stage (#51): a conservative linear lift for quiet room mics.

Synthetic signals only (seeded numpy): no recordings, no models, CPU-only."""

import time

import numpy as np
import pytest

from tuparles.config import SAMPLE_RATE
from tuparles.preprocess import (
    MAX_GAIN_DB,
    TARGET_SPEECH_DBFS,
    far_field_gain,
    prepare_pcm,
)

FRAME = 320  # 20 ms at 16 kHz


def _band_noise(n: int, rng: np.random.RandomState) -> np.ndarray:
    """White noise brick-wall filtered to 100-3000 Hz, unit RMS."""
    spec = np.fft.rfft(rng.randn(n))
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    spec[(freqs < 100) | (freqs > 3000)] = 0
    x = np.fft.irfft(spec, n)
    return x / np.sqrt(np.mean(x**2))


def _speech_like(
    seconds: float, speech_rms_db: float, floor_below_db: float = 25.0, seed: int = 0
) -> np.ndarray:
    """float64 [-1, 1]: 0.4 s syllabic (4 Hz AM) bursts every 0.7 s over a floor.

    `speech_rms_db` is the RMS (dBFS) inside the bursts."""
    rng = np.random.RandomState(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    am = 0.55 + 0.45 * np.sin(2 * np.pi * 4.0 * t) ** 2
    bursts = ((t % 0.7) < 0.4).astype(np.float64)
    speech = _band_noise(n, rng) * am * bursts
    speech *= 10 ** (speech_rms_db / 20) / np.sqrt(np.mean(speech[bursts > 0] ** 2))
    floor = _band_noise(n, rng) * 10 ** ((speech_rms_db - floor_below_db) / 20)
    return speech + floor


def _to_i16(x: np.ndarray) -> np.ndarray:
    return np.round(np.clip(x, -1, 1) * 32768.0).clip(-32768, 32767).astype(np.int16)


def _f(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float64) / (32768.0 if x.dtype == np.int16 else 1.0)


def _speech_db(x: np.ndarray) -> float:
    """Independent re-statement of the stage's speech level: power-mean of the
    frames at or above the 70th percentile of frame RMS."""
    f = _f(x)
    n = f.size // FRAME
    p = (f[: n * FRAME].reshape(n, FRAME) ** 2).mean(axis=1)
    db = 10 * np.log10(np.maximum(p, 1e-12))
    return float(10 * np.log10(p[db >= np.percentile(db, 70)].mean()))


def _peak_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.abs(_f(x)).max()))


class TestLifts:
    def test_quiet_speech_lifted_toward_target(self):
        # -48 dBFS RMS overall: the laptop-array-in-a-meeting-room case.
        sig = _speech_like(8.0, speech_rms_db=-46.0)
        pcm = _to_i16(sig)
        out, gain = far_field_gain(pcm)
        assert gain > 3.0
        assert abs(_speech_db(out) - TARGET_SPEECH_DBFS) <= 2.0
        assert _peak_db(out) <= -1.0 + 0.05
        # returned gain is the gain actually applied (single linear gain)
        applied = 20 * np.log10(np.abs(_f(out)).max() / np.abs(_f(pcm)).max())
        assert applied == pytest.approx(gain, abs=0.1)

    def test_peak_ceiling_limits_gain(self):
        # Quiet speech plus one tall transient: the lift stops at -1 dBFS peak
        # instead of clipping, and no compression squashes the click.
        sig = _speech_like(6.0, speech_rms_db=-44.0)
        sig[8000] = 10 ** (-14.0 / 20)  # a -14 dBFS click
        out, gain = far_field_gain(_to_i16(sig))
        assert _peak_db(out) <= -1.0 + 0.05
        assert gain < MAX_GAIN_DB
        assert gain == pytest.approx(13.0, abs=0.2)  # -1 - (-14)

    def test_gain_never_exceeds_max_and_is_clamped(self):
        # -66 dBFS speech wants +40 dB; the cap holds it at MAX_GAIN_DB.
        sig = _speech_like(8.0, speech_rms_db=-66.0, seed=3)
        out, gain = far_field_gain(_to_i16(sig))
        assert gain == pytest.approx(MAX_GAIN_DB, abs=1e-6)
        assert _peak_db(out) <= -1.0 + 0.05

    def test_very_quiet_structure_is_not_blown_up(self):
        # -75 dBFS is under the digital-silence floor: never amplified at all.
        pcm = _to_i16(_speech_like(8.0, speech_rms_db=-75.0, seed=4))
        out, gain = far_field_gain(pcm)
        assert gain <= MAX_GAIN_DB
        assert gain == 0.0
        assert np.array_equal(out, pcm)


class TestNoOps:
    def test_loud_near_field_is_byte_identical(self):
        pcm = _to_i16(_speech_like(6.0, speech_rms_db=-18.0, seed=5))
        out, gain = far_field_gain(pcm)
        assert gain == 0.0
        assert out.dtype == pcm.dtype
        assert np.array_equal(out, pcm)

    def test_just_loud_enough_is_untouched(self):
        pcm = _to_i16(_speech_like(6.0, speech_rms_db=-29.0, seed=6))
        out, gain = far_field_gain(pcm)
        assert gain == 0.0 and np.array_equal(out, pcm)

    def test_pure_noise_untouched(self):
        # Stationary room hiss at a quiet level: no speech structure, so no lift.
        rng = np.random.RandomState(7)
        pcm = _to_i16(rng.randn(8 * SAMPLE_RATE) * 10 ** (-48 / 20))
        out, gain = far_field_gain(pcm)
        assert gain == 0.0 and np.array_equal(out, pcm)

    def test_weak_structure_over_floor_untouched(self):
        # Speech no louder than the floor (< 8 dB over it): amplifying would lift noise.
        pcm = _to_i16(_speech_like(8.0, speech_rms_db=-46.0, floor_below_db=0.0))
        out, gain = far_field_gain(pcm)
        assert gain == 0.0 and np.array_equal(out, pcm)

    @pytest.mark.parametrize("dtype", [np.int16, np.float32])
    def test_digital_silence_untouched_no_nan(self, dtype):
        pcm = np.zeros(4 * SAMPLE_RATE, dtype=dtype)
        out, gain = far_field_gain(pcm)
        assert gain == 0.0
        assert np.array_equal(out, pcm)
        assert np.isfinite(_f(out)).all()

    def test_too_short_untouched(self):
        pcm = _to_i16(_speech_like(0.45, speech_rms_db=-46.0))  # < 25 frames
        out, gain = far_field_gain(pcm)
        assert gain == 0.0 and np.array_equal(out, pcm)

    def test_empty_untouched(self):
        pcm = np.zeros(0, dtype=np.int16)
        out, gain = far_field_gain(pcm)
        assert gain == 0.0 and out.size == 0

    def test_disabled_is_noop(self):
        pcm = _to_i16(_speech_like(8.0, speech_rms_db=-46.0))
        out, gain = far_field_gain(pcm, enabled=False)
        assert gain == 0.0 and np.array_equal(out, pcm)


class TestDtypes:
    def test_int16_in_int16_out_without_wraparound(self):
        pcm = _to_i16(_speech_like(8.0, speech_rms_db=-46.0))
        out, gain = far_field_gain(pcm)
        assert gain > 0 and out.dtype == np.int16
        # no sign flip from wraparound: where the input is clearly positive the
        # output is positive, and the ceiling holds in int16 units too
        assert int(np.abs(out.astype(np.int32)).max()) <= int(0.8913 * 32768) + 1
        big = np.abs(pcm) > 20
        assert np.all(np.sign(out[big]) == np.sign(pcm[big]))

    def test_float32_in_float32_out(self):
        pcm = _speech_like(8.0, speech_rms_db=-46.0).astype(np.float32)
        out, gain = far_field_gain(pcm)
        assert gain > 0 and out.dtype == np.float32
        assert float(np.abs(out).max()) <= 0.8913 + 1e-4

    def test_input_not_mutated(self):
        pcm = _to_i16(_speech_like(8.0, speech_rms_db=-46.0))
        before = pcm.copy()
        far_field_gain(pcm)
        assert np.array_equal(pcm, before)


def test_fast_enough():
    pcm = _to_i16(_speech_like(30.0, speech_rms_db=-46.0))
    t0 = time.perf_counter()
    far_field_gain(pcm)
    assert time.perf_counter() - t0 < 0.5  # spec says <50 ms; CI-generous


class TestPrepareSeam:
    """prepare_pcm runs the stage first, gated by the `far_field_gain` setting."""

    def test_on_lifts_quiet_take(self, monkeypatch):
        import tuparles.preprocess as pp

        monkeypatch.setattr(pp, "_far_field_gain_on", lambda: True)
        monkeypatch.setattr(pp, "_speech_leveler_on", lambda: False)
        pcm = _to_i16(_speech_like(8.0, speech_rms_db=-46.0))
        lifted = far_field_gain(pcm)[0]
        out = prepare_pcm(pcm)
        assert out.dtype == np.float32
        # peak normalization afterwards is the same whatever the gain was, but
        # the stage ran first: the result equals prepare on the lifted buffer.
        monkeypatch.setattr(pp, "_far_field_gain_on", lambda: False)
        assert np.array_equal(out, prepare_pcm(lifted))

    def test_off_is_historical_path(self, monkeypatch):
        import tuparles.preprocess as pp

        monkeypatch.setattr(pp, "_far_field_gain_on", lambda: False)
        monkeypatch.setattr(pp, "_speech_leveler_on", lambda: False)
        pcm = _to_i16(_speech_like(8.0, speech_rms_db=-46.0))
        expect = pp.normalize_audio(pcm.astype(np.float32) / 32768.0)
        assert np.array_equal(prepare_pcm(pcm), expect)

    def test_gain_is_surfaced_only_when_applied(self, monkeypatch):
        import tuparles.preprocess as pp

        monkeypatch.setattr(pp, "_far_field_gain_on", lambda: True)
        prepare_pcm(_to_i16(_speech_like(8.0, speech_rms_db=-46.0)))
        assert pp.last_far_field_gain_db > 3.0
        prepare_pcm(_to_i16(_speech_like(6.0, speech_rms_db=-18.0, seed=5)))
        assert pp.last_far_field_gain_db == 0.0

    def test_probe_reads_setting(self, monkeypatch):
        import tuparles.preprocess as pp
        from tuparles import settings

        monkeypatch.setattr(settings, "get", lambda k: k == "far_field_gain")
        assert pp._far_field_gain_on() is True
        monkeypatch.setattr(settings, "get", lambda k: False)
        assert pp._far_field_gain_on() is False

    def test_setting_defaults_on(self):
        from tuparles import settings

        assert settings._DEFAULTS["far_field_gain"] is True


class TestTrimSeam:
    """`trim_silence` decides on far-field-LIFTED audio but slices the ORIGINAL.

    Trim and decode must agree on what counts as speech: a take at -48 dBFS
    trims to the same span as the same take 28 dB louder. The RMS fallback tier
    is forced (silero is an optional dep, and a synthetic burst is not speech to
    it); the lift is applied identically ahead of either tier."""

    @pytest.fixture(autouse=True)
    def _rms_tier(self, monkeypatch):
        import tuparles.preprocess as pp

        monkeypatch.setattr(pp, "_silero_unavailable", True)
        monkeypatch.setattr(pp, "_far_field_gain_on", lambda: True)

    @staticmethod
    def _take(speech_rms_db: float) -> np.ndarray:
        """0.8 s floor, 2 s speech-like bursts, 0.8 s floor — as float64."""
        floor_db = speech_rms_db - 40.0
        rng = np.random.RandomState(11)
        lead = _band_noise(int(0.8 * SAMPLE_RATE), rng) * 10 ** (floor_db / 20)
        tail = _band_noise(int(0.8 * SAMPLE_RATE), rng) * 10 ** (floor_db / 20)
        return np.concatenate(
            [lead, _speech_like(2.0, speech_rms_db, 40.0, seed=12), tail]
        )

    @staticmethod
    def _span(orig: np.ndarray, out: np.ndarray) -> tuple[int, int]:
        """Where `out` sits inside `orig` (it must be a contiguous slice)."""
        for start in range(0, orig.size - out.size + 1, 1):
            if orig[start] == out[0] and np.array_equal(
                orig[start : start + out.size], out
            ):
                return start, start + out.size
        raise AssertionError("trim output is not a slice of the original")

    def test_quiet_and_loud_takes_trim_to_the_same_span(self):
        from tuparles.preprocess import trim_silence

        quiet = _to_i16(self._take(-46.0))  # about -48 dBFS RMS overall
        loud = _to_i16(self._take(-46.0) * 10 ** (28.0 / 20))  # about -20 dBFS
        oq, ol = trim_silence(quiet), trim_silence(loud)
        assert oq.size < quiet.size and ol.size < loud.size  # both really trimmed
        (sq, eq), (sl, el) = self._span(quiet, oq), self._span(loud, ol)
        tol = int(0.040 * SAMPLE_RATE)
        assert abs(sq - sl) <= tol and abs(eq - el) <= tol

    def test_very_quiet_take_is_trimmed_not_judged_silent(self):
        # Peak ~ -48 dBFS: under the RMS tier's absolute silence floor unlifted,
        # so the old behaviour handed back the whole buffer. Lifted, it trims.
        from tuparles.preprocess import trim_silence

        quiet = _to_i16(self._take(-64.0))
        out = trim_silence(quiet)
        assert out.size < quiet.size

    def test_returns_slice_of_original_unlifted_int16(self):
        from tuparles.preprocess import trim_silence

        quiet = _to_i16(self._take(-46.0))
        out = trim_silence(quiet)
        assert out.dtype == np.int16 and out.size < quiet.size
        self._span(quiet, out)  # values untouched: array_equal to a source slice
        assert _peak_db(out) < -25.0  # still quiet: the lift is NOT baked in

    def test_float32_is_a_slice_of_the_original(self):
        from tuparles.preprocess import trim_silence

        quiet = self._take(-46.0).astype(np.float32)
        out = trim_silence(quiet)
        assert out.dtype == np.float32 and out.size < quiet.size
        self._span(quiet, out)

    def test_setting_off_keeps_the_old_decision(self, monkeypatch):
        import tuparles.preprocess as pp

        monkeypatch.setattr(pp, "_far_field_gain_on", lambda: False)
        # Very quiet take: under the absolute RMS floor, so untouched, as before.
        very_quiet = _to_i16(self._take(-64.0))
        assert np.array_equal(pp.trim_silence(very_quiet), very_quiet)
        # Quiet-but-above-floor take: the scale-free RMS gate, unchanged.
        quiet = _to_i16(self._take(-46.0))
        out = pp.trim_silence(quiet)
        assert out.size < quiet.size
        assert out.size == 38880  # pinned: the pre-#51 result for this take

    def test_low_level_noise_is_left_alone(self):
        # No speech structure: the lift no-ops and the RMS gate still finds
        # nothing worth cutting.
        from tuparles.preprocess import trim_silence

        rng = np.random.RandomState(13)
        pcm = _to_i16(rng.randn(4 * SAMPLE_RATE) * 10 ** (-48 / 20))
        assert np.array_equal(trim_silence(pcm), pcm)
