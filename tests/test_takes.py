import wave

import numpy as np

from tuparles import takes


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Config too: with TUPARLES_DEV unset the gate falls back to the
    # `dev_recording` SETTING, so a box whose real Réglages legitimately
    # enabled dev capture must not leak into the "disabled" tests.
    monkeypatch.setenv("TUPARLES_CONFIG_DIR", str(tmp_path / "config"))


def _audio(seconds=0.5, rate=takes.SAMPLE_RATE):
    return (np.random.default_rng(0).integers(-2000, 2000, int(seconds * rate))).astype(
        np.int16
    )


class TestGate:
    def test_disabled_by_default(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)  # a real Réglages opt-in must not leak in
        monkeypatch.delenv("TUPARLES_DEV", raising=False)
        assert not takes.dev_recording_enabled()

    def test_falsey_values_stay_off(self, monkeypatch):
        for val in ("", "0", "false", "no", "off", "  Off "):
            monkeypatch.setenv("TUPARLES_DEV", val)
            assert not takes.dev_recording_enabled(), val

    def test_truthy_values_turn_on(self, monkeypatch):
        for val in ("1", "true", "yes", "on"):
            monkeypatch.setenv("TUPARLES_DEV", val)
            assert takes.dev_recording_enabled(), val


class TestGateSettingFallback:
    """#8: with TUPARLES_DEV unset, the Réglages `dev_recording` setting decides;
    the env var, when SET, overrides it either way."""

    def _iso(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("TUPARLES_DEV", raising=False)

    def test_setting_off_is_off(self, tmp_path, monkeypatch):
        self._iso(tmp_path, monkeypatch)
        from tuparles import settings

        settings.put("dev_recording", False)
        assert not takes.dev_recording_enabled()

    def test_setting_on_turns_on(self, tmp_path, monkeypatch):
        self._iso(tmp_path, monkeypatch)
        from tuparles import settings

        settings.put("dev_recording", True)
        assert takes.dev_recording_enabled()

    def test_env_falsey_overrides_setting_on(self, tmp_path, monkeypatch):
        self._iso(tmp_path, monkeypatch)
        from tuparles import settings

        settings.put("dev_recording", True)
        monkeypatch.setenv("TUPARLES_DEV", "0")  # env present → it wins → off
        assert not takes.dev_recording_enabled()

    def test_env_truthy_overrides_setting_off(self, tmp_path, monkeypatch):
        self._iso(tmp_path, monkeypatch)
        from tuparles import settings

        settings.put("dev_recording", False)
        monkeypatch.setenv("TUPARLES_DEV", "1")  # env present → it wins → on
        assert takes.dev_recording_enabled()


class TestSaveTake:
    def test_noop_when_disabled(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.delenv("TUPARLES_DEV", raising=False)
        assert takes.save_take(1, _audio()) is None
        assert not takes.takes_dir().exists()

    def test_noop_on_empty_audio(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("TUPARLES_DEV", "1")
        assert takes.save_take(1, np.array([], dtype=np.int16)) is None

    def test_writes_keyed_16k_mono_s16(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("TUPARLES_DEV", "1")
        path = takes.save_take(42, _audio(seconds=0.25))
        assert path is not None and path.name == "42.wav"
        with wave.open(str(path), "rb") as w:
            assert w.getframerate() == 16_000
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2  # int16, exactly what the engine wants

    def test_prune_evicts_oldest_past_budget(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("TUPARLES_DEV", "1")
        # tiny budget: each ~1 s take ≈ 32 KB, so 40 KB holds ~one
        monkeypatch.setattr(takes, "_BYTES_BUDGET", 40 * 1024)
        for i in range(5):
            takes.save_take(i, _audio(seconds=1.0))
        survivors = sorted(p.stem for p in takes.takes_dir().glob("*.wav"))
        # the newest survives; the oldest were evicted to stay under budget
        assert "4" in survivors
        assert "0" not in survivors
        assert len(survivors) < 5


class TestSaveMiss:
    def test_noop_when_disabled(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.delenv("TUPARLES_DEV", raising=False)
        assert takes.save_miss(_audio()) is None
        assert not takes.misses_dir().exists()

    def test_noop_on_empty_audio(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("TUPARLES_DEV", "1")
        assert takes.save_miss(np.array([], dtype=np.int16)) is None

    def test_writes_timestamped_16k_mono_s16(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("TUPARLES_DEV", "1")
        path = takes.save_miss(_audio(seconds=0.25))
        assert path is not None
        assert path.parent == takes.misses_dir()
        assert path.name.startswith("miss-") and path.suffix == ".wav"
        with wave.open(str(path), "rb") as w:
            assert w.getframerate() == 16_000
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2

    def test_misses_live_under_takes_dir(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert takes.misses_dir().parent == takes.takes_dir()

    def test_prune_evicts_oldest_past_budget(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("TUPARLES_DEV", "1")
        monkeypatch.setattr(takes, "_MISS_BYTES_BUDGET", 40 * 1024)
        for _ in range(5):
            takes.save_miss(_audio(seconds=1.0))
        survivors = list(takes.misses_dir().glob("*.wav"))
        total = sum(p.stat().st_size for p in survivors)
        assert total <= 40 * 1024
        assert len(survivors) < 5
