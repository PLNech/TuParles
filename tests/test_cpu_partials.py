"""CPU live partials (#127): qwen can't stream, so the CPU bubble's preview
comes from a separate small whisper. These pin the wiring (opt-out, lazy build,
graceful degrade, and the post-fallback delegation) WITHOUT loading a real
model — the small model is injected as a fake factory."""

import numpy as np

from tuparles.engine import QwenCpuEngine, ResilientEngine, Transcription

AUDIO = np.zeros(16_000, dtype=np.int16)


class FakePartials:
    """Stands in for CpuPartialsEngine — no weights, just counts calls."""

    def __init__(self):
        self.calls = 0

    def transcribe_partial(self, audio):
        self.calls += 1
        return "cpu-partial"


def test_cpu_streams_partials_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # defaults → enabled
    eng = QwenCpuEngine(partials_factory=FakePartials)
    assert eng.supports_partials is True
    assert eng.transcribe_partial(AUDIO) == "cpu-partial"


def test_cpu_partials_are_opt_out(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from tuparles import settings

    settings.put("cpu_partials_enabled", False)
    built = []
    eng = QwenCpuEngine(partials_factory=lambda: built.append(1) or FakePartials())
    assert eng.supports_partials is False
    assert eng.transcribe_partial(AUDIO) == ""
    assert built == []  # disabled → never even builds the small model


def test_cpu_partials_degrade_to_waveform_when_model_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    attempts = []

    def boom():
        attempts.append(1)
        raise RuntimeError("no weights cached and no network on the train")

    eng = QwenCpuEngine(partials_factory=boom)
    assert eng.transcribe_partial(AUDIO) == ""  # no crash, waveform-only
    assert eng.transcribe_partial(AUDIO) == ""  # still ""
    assert len(attempts) == 1  # failure cached — doesn't retry every partial


def test_resilient_uses_cpu_partials_after_sticky_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class DeadGpu:
        supports_partials = True

        def transcribe(self, audio):
            raise RuntimeError("CUDA failed with error out of memory")

        def transcribe_partial(self, audio):
            raise RuntimeError("CUDA failed")

    cpu = QwenCpuEngine(partials_factory=FakePartials)
    eng = ResilientEngine(gpu_factory=DeadGpu, cpu_factory=lambda: cpu)
    eng.transcribe(AUDIO)  # GPU dead + rebuild dead → sticky CPU
    assert eng.active_backend == "cpu"
    assert eng.supports_partials is True  # CPU now streams (was False pre-#127)
    assert eng.transcribe_partial(AUDIO) == "cpu-partial"


def test_cpu_partial_window_defaults_short(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from tuparles.config import PARTIAL_WINDOW_S

    # CPU window is deliberately shorter than the GPU one (code-switch tracking).
    assert QwenCpuEngine().partial_window_s == 6
    assert QwenCpuEngine().partial_window_s < PARTIAL_WINDOW_S


def test_cpu_partial_window_is_a_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from tuparles import settings

    settings.put("cpu_partials_window_s", 10)
    assert QwenCpuEngine().partial_window_s == 10  # hot-read, no restart


def test_resilient_window_follows_live_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from tuparles.config import PARTIAL_WINDOW_S

    class DeadGpu:
        supports_partials = True

        def transcribe(self, audio):
            raise RuntimeError("CUDA failed with error unknown error")

        def transcribe_partial(self, audio):
            raise RuntimeError("CUDA failed")

    cpu = QwenCpuEngine(partials_factory=FakePartials)
    eng = ResilientEngine(gpu_factory=DeadGpu, cpu_factory=lambda: cpu)
    assert eng.partial_window_s == PARTIAL_WINDOW_S  # GPU still presumed live → long
    eng.transcribe(AUDIO)  # GPU dies → sticky CPU
    assert eng.active_backend == "cpu"
    assert eng.partial_window_s == 6  # now follows the CPU engine's short window


def test_gpu_partials_untouched_by_cpu_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from tuparles import settings

    settings.put("cpu_partials_enabled", False)  # CPU off must not gag the GPU

    class LiveGpu:
        supports_partials = True

        def transcribe(self, audio):
            return Transcription("gpu")

        def transcribe_partial(self, audio):
            return "gpu-partial"

    eng = ResilientEngine(gpu_factory=LiveGpu, cpu_factory=lambda: QwenCpuEngine())
    assert eng.supports_partials is True
    assert eng.transcribe_partial(AUDIO) == "gpu-partial"
