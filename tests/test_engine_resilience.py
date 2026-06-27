"""ResilientEngine: mid-session CUDA recovery without a real GPU.

Models the laptop suspend/resume failure mode — a context that loads fine,
decodes, then throws on every call until rebuilt.
"""

import numpy as np

from tuparles.engine import ResilientEngine, Transcription

AUDIO = np.zeros(16_000, dtype=np.int16)


class FakeGpu:
    """A GPU engine whose decodes throw after `dies_after` successful calls.
    Each *instance* is a fresh CUDA context, so a rebuild = a new FakeGpu."""

    supports_partials = True

    def __init__(self, dies_after=10**9, partial="p"):
        self._left = dies_after
        self._partial = partial

    def transcribe(self, audio, context=None):
        if self._left <= 0:
            raise RuntimeError("CUDA failed with error out of memory")
        self._left -= 1
        return Transcription("gpu", language="fr")

    def transcribe_partial(self, audio):
        if self._left <= 0:
            raise RuntimeError("CUDA failed")
        return self._partial


class FakeCpu:
    supports_partials = False

    def transcribe(self, audio, context=None):
        return Transcription("cpu")


def _engine(gpu_factory):
    return ResilientEngine(gpu_factory=gpu_factory, cpu_factory=FakeCpu)


def test_healthy_gpu_stays_on_gpu():
    eng = _engine(lambda: FakeGpu())
    assert eng.transcribe(AUDIO).text == "gpu"
    assert eng.engine_name == "GpuEngine"
    assert eng.supports_partials is True
    assert eng.active_backend == "gpu"  # bubble/tray colour stays green


def test_suspend_resume_recovers_by_rebuilding_context():
    # First context dies immediately; the rebuild yields a fresh, working one.
    built = []

    def factory():
        # context #0 dies at once; every rebuilt context is healthy
        g = FakeGpu(dies_after=0 if not built else 10**9)
        built.append(g)
        return g

    eng = _engine(factory)
    # decode throws on the stale context, rebuilds, retries → GPU result
    assert eng.transcribe(AUDIO).text == "gpu"
    assert eng.engine_name == "GpuEngine"  # recovered, still on GPU
    assert len(built) == 2  # original + one rebuild


def test_dead_gpu_falls_back_to_cpu_for_the_session():
    # First build (in __init__) succeeds but its context is dead; the rebuild
    # also fails (GPU genuinely gone) → CPU for the rest of the session.
    seq = [FakeGpu(dies_after=0)]

    def factory():
        if seq:
            return seq.pop()
        raise RuntimeError("no CUDA device")

    eng = _engine(factory)
    assert eng.active_backend == "gpu"  # green until the GPU actually gives up
    assert eng.transcribe(AUDIO).text == "cpu"  # rebuild failed → CPU
    assert eng.engine_name == "QwenCpuEngine"
    assert eng.supports_partials is False
    assert eng.active_backend == "cpu"  # now blue, sticky for the session
    # stays on CPU without retrying the GPU
    assert eng.transcribe(AUDIO).text == "cpu"


def test_partial_failure_is_silent_and_does_not_fall_back():
    eng = _engine(lambda: FakeGpu(dies_after=0))
    assert eng.transcribe_partial(AUDIO) == ""  # swallowed
    assert eng.engine_name == "GpuEngine"  # no fallback triggered by a partial
