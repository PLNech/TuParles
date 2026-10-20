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
    # Names the rung that actually decoded, not a hardcoded guess: CPU used to
    # be a rare fallback, but it can now be the deliberate choice (prefer_cpu),
    # so mislabelling it would be the common case rather than a rare white lie.
    assert eng.engine_name == "FakeCpu"
    assert eng.supports_partials is False
    assert eng.active_backend == "cpu"  # now blue, sticky for the session
    # stays on CPU without retrying the GPU
    assert eng.transcribe(AUDIO).text == "cpu"


def test_partial_failure_is_silent_and_does_not_fall_back():
    eng = _engine(lambda: FakeGpu(dies_after=0))
    assert eng.transcribe_partial(AUDIO) == ""  # swallowed
    assert eng.engine_name == "GpuEngine"  # no fallback triggered by a partial


class _LangGpu:
    """A backend that tracks how many times its sticky language was reset."""

    supports_partials = True

    def __init__(self):
        self.resets = 0

    def transcribe(self, audio, context=None):
        return Transcription("gpu", language="fr")

    def reset_partial_language(self):
        self.resets += 1


class _LangCpu(_LangGpu):
    supports_partials = False

    def transcribe(self, audio, context=None):
        return Transcription("cpu")


def test_reset_partial_language_does_not_force_build_cpu():
    # On GPU with the CPU engine never used: reset the GPU, but do NOT build the
    # heavy CPU fallback just to clear state it doesn't yet hold.
    built = []
    gpu = _LangGpu()
    eng = ResilientEngine(
        gpu_factory=lambda: gpu,
        cpu_factory=lambda: built.append(_LangCpu()) or built[-1],
    )
    eng.reset_partial_language()
    assert gpu.resets == 1
    assert built == []  # CPU fallback not force-loaded


def test_reset_partial_language_clears_both_backends_when_cpu_built():
    # Once the CPU engine exists (a mid-session fallback built it), a take-start
    # reset must clear BOTH — so a GPU-start take that later falls back to CPU
    # can't inherit the previous take's sticky language across the boundary.
    gpu, cpu = _LangGpu(), _LangCpu()
    eng = ResilientEngine(gpu_factory=lambda: gpu, cpu_factory=lambda: cpu)
    eng._cpu_engine()  # force the CPU engine into existence, as a fallback would
    gpu.resets = cpu.resets = 0
    eng.reset_partial_language()
    assert gpu.resets == 1  # reset even though the GPU is still live
    assert cpu.resets == 1  # the already-built CPU is cleared too


class TestPreferCpu:
    """« Préférer le CPU » — leave the card to whoever else needs it (#137).

    The point is not "fall back to CPU", which the engine could already do.
    The point is that the CUDA engine is never *constructed*: `GpuEngine()`
    preloads the CUDA libs and allocates VRAM in its constructor, so building
    it and then standing down would still take the memory the user is trying
    to free.
    """

    def _counting_factory(self):
        calls = []

        def factory():
            calls.append(1)
            return FakeGpu()

        return factory, calls

    def test_the_gpu_is_never_constructed(self, monkeypatch):
        from tuparles import settings

        settings.put("prefer_cpu", True)
        factory, calls = self._counting_factory()

        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)

        # The discriminating assertion. "It decoded on CPU" would also pass
        # with a GPU that was built and then abandoned, VRAM and all.
        assert calls == [], "prefer_cpu built a CUDA engine anyway"
        assert eng.active_backend == "cpu"  # bubble/tray go blue, honestly
        assert eng.transcribe(AUDIO).text == "cpu"
        assert calls == []

    def test_toggling_on_mid_session_releases_the_card(self):
        from tuparles import settings

        settings.put("prefer_cpu", False)
        eng = ResilientEngine(gpu_factory=lambda: FakeGpu(), cpu_factory=FakeCpu)
        assert eng.transcribe(AUDIO).text == "gpu"

        settings.put("prefer_cpu", True)  # your friend starts training
        assert eng.transcribe(AUDIO).text == "cpu"
        assert eng.active_backend == "cpu"
        # Released, not merely unused — nothing holds the context any more.
        assert eng._gpu is None

    def test_toggling_off_again_reclaims_the_gpu(self):
        from tuparles import settings

        settings.put("prefer_cpu", True)
        factory, calls = self._counting_factory()
        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)
        assert eng.transcribe(AUDIO).text == "cpu"
        assert calls == []

        settings.put("prefer_cpu", False)  # training's done, take it back
        assert eng.transcribe(AUDIO).text == "gpu"
        assert eng.active_backend == "gpu"
        assert len(calls) == 1  # built exactly when first needed, not before

    def test_a_genuinely_dead_gpu_is_not_resurrected_by_the_preference(self):
        """The reason for tracking *why* we're on CPU.

        A session that fell back because CUDA died must stay on CPU. Toggling
        prefer_cpu off is not evidence the card came back — and retrying a
        dead one would break every take.
        """
        from tuparles import settings

        settings.put("prefer_cpu", False)
        seq = [FakeGpu(dies_after=0)]

        def factory():
            if seq:
                return seq.pop()
            raise RuntimeError("no CUDA device")

        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)
        assert eng.transcribe(AUDIO).text == "cpu"  # died, rebuild failed
        assert eng._on_cpu_reason == "failure"

        # Someone ticks and unticks the box: still CPU, because the card is gone.
        settings.put("prefer_cpu", True)
        assert eng.transcribe(AUDIO).text == "cpu"
        settings.put("prefer_cpu", False)
        assert eng.transcribe(AUDIO).text == "cpu"
        assert eng.active_backend == "cpu"

    def test_a_failed_reclaim_stops_retrying(self):
        """Lifting the preference onto a broken card must not cost ~1.6 s a take."""
        from tuparles import settings

        settings.put("prefer_cpu", True)
        calls = []

        def factory():
            calls.append(1)
            raise RuntimeError("no CUDA device")

        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)
        assert calls == []

        settings.put("prefer_cpu", False)
        assert eng.transcribe(AUDIO).text == "cpu"
        assert len(calls) == 1  # tried once…
        assert eng.transcribe(AUDIO).text == "cpu"
        assert eng.transcribe(AUDIO).text == "cpu"
        assert len(calls) == 1  # …and then stopped asking

    def test_partials_honour_the_preference_from_the_same_take(self):
        """The daemon probes supports_partials at take start, so the take you
        toggle on must not still preview against the card."""
        from tuparles import settings

        settings.put("prefer_cpu", False)
        eng = ResilientEngine(gpu_factory=lambda: FakeGpu(), cpu_factory=FakeCpu)
        assert eng.supports_partials is True  # GPU partials

        settings.put("prefer_cpu", True)
        assert eng.supports_partials is False  # FakeCpu has none
        assert eng._gpu is None


class TestBatteryAware:
    """« Économiser la batterie » — on battery, behave as if prefer_cpu were set.

    The probe is injected (monkeypatched `tuparles.power.on_battery`), never the
    real sysfs: the suite must not care whether the dev laptop is plugged in.
    conftest pins it to "on AC" for every other test.
    """

    @staticmethod
    def _plug(monkeypatch, state):
        from tuparles import power

        monkeypatch.setattr(power, "on_battery", lambda: state["battery"])

    @staticmethod
    def _counting_factory():
        calls = []

        def factory():
            calls.append(1)
            return FakeGpu()

        return factory, calls

    def test_on_battery_starts_on_cpu_without_touching_the_card(self, monkeypatch):
        self._plug(monkeypatch, {"battery": True})
        factory, calls = self._counting_factory()
        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)

        assert calls == [], "on battery, yet a CUDA engine was built"
        assert eng.active_backend == "cpu"  # tray/bubble go blue
        assert eng._on_cpu_reason == "preference"  # reversible, not a failure
        assert eng.cpu_reason == "battery"  # and we know why, for the toast/log
        assert eng.transcribe(AUDIO).text == "cpu"
        assert calls == []

    def test_on_ac_uses_the_gpu(self, monkeypatch):
        self._plug(monkeypatch, {"battery": False})
        eng = ResilientEngine(gpu_factory=lambda: FakeGpu(), cpu_factory=FakeCpu)
        assert eng.active_backend == "gpu"
        assert eng.cpu_reason is None
        assert eng.transcribe(AUDIO).text == "gpu"

    def test_setting_off_ignores_the_battery(self, monkeypatch):
        from tuparles import settings

        settings.put("battery_aware", False)
        self._plug(monkeypatch, {"battery": True})
        eng = ResilientEngine(gpu_factory=lambda: FakeGpu(), cpu_factory=FakeCpu)
        assert eng.active_backend == "gpu"
        assert eng.transcribe(AUDIO).text == "gpu"

    def test_battery_aware_is_on_by_default(self):
        from tuparles import settings

        assert settings.get("battery_aware") is True

    def test_prefer_cpu_still_wins_on_ac(self, monkeypatch):
        from tuparles import settings

        settings.put("prefer_cpu", True)
        self._plug(monkeypatch, {"battery": False})
        factory, calls = self._counting_factory()
        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)
        assert eng.transcribe(AUDIO).text == "cpu"
        assert eng.cpu_reason == "preference"
        assert calls == []

    def test_plugging_in_with_prefer_cpu_set_stays_on_cpu(self, monkeypatch):
        from tuparles import settings

        settings.put("prefer_cpu", True)
        state = {"battery": True}
        self._plug(monkeypatch, state)
        factory, calls = self._counting_factory()
        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)
        assert eng.transcribe(AUDIO).text == "cpu"

        state["battery"] = False  # charger in, but the user still wants CPU
        assert eng.transcribe(AUDIO).text == "cpu"
        assert eng.cpu_reason == "preference"
        assert calls == []

    def test_a_failed_gpu_is_not_resurrected_by_plugging_in(self, monkeypatch):
        state = {"battery": False}
        self._plug(monkeypatch, state)
        seq = [FakeGpu(dies_after=0)]
        calls = []

        def factory():
            calls.append(1)
            if seq:
                return seq.pop()
            raise RuntimeError("no CUDA device")

        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)
        assert eng.transcribe(AUDIO).text == "cpu"  # died, rebuild failed
        assert eng._on_cpu_reason == "failure"
        built = len(calls)

        state["battery"] = True  # unplugged…
        assert eng.transcribe(AUDIO).text == "cpu"
        state["battery"] = False  # …and back on AC: still a dead card
        assert eng.transcribe(AUDIO).text == "cpu"
        assert eng._on_cpu_reason == "failure"
        assert eng.cpu_reason == "failure"
        assert len(calls) == built, "a mains flip retried a dead GPU"

    def test_battery_ac_battery_round_trip(self, monkeypatch):
        state = {"battery": True}
        self._plug(monkeypatch, state)
        factory, calls = self._counting_factory()
        eng = ResilientEngine(gpu_factory=factory, cpu_factory=FakeCpu)
        assert eng.transcribe(AUDIO).text == "cpu"
        assert calls == []  # never built on battery

        state["battery"] = False  # plugged in at the customer's desk
        assert eng.transcribe(AUDIO).text == "gpu"
        assert eng.active_backend == "gpu"
        assert eng.cpu_reason is None
        assert len(calls) == 1  # built lazily, exactly when first needed

        state["battery"] = True  # unplugged for the walk to the meeting room
        assert eng.transcribe(AUDIO).text == "cpu"
        assert eng._gpu is None  # released, VRAM and all
        assert eng.cpu_reason == "battery"

        state["battery"] = False
        assert eng.transcribe(AUDIO).text == "gpu"
        assert len(calls) == 2  # rebuilt once per return to AC, not per take
        assert eng.transcribe(AUDIO).text == "gpu"
        assert len(calls) == 2

    def test_partials_follow_the_power_state_from_the_same_take(self, monkeypatch):
        state = {"battery": False}
        self._plug(monkeypatch, state)
        eng = ResilientEngine(gpu_factory=lambda: FakeGpu(), cpu_factory=FakeCpu)
        assert eng.supports_partials is True  # GPU partials

        state["battery"] = True
        assert eng.supports_partials is False  # FakeCpu has none
        assert eng._gpu is None

    def test_an_unplug_mid_take_lands_at_the_final_decode(self, monkeypatch):
        """The preference is synced at take start (supports_partials) and at the
        final (transcribe), never per partial: partials are frequent and must
        not thrash a GPU release/rebuild. So an unplug mid-take keeps the live
        previews on the GPU and moves the final decode to CPU."""
        state = {"battery": False}
        self._plug(monkeypatch, state)
        eng = ResilientEngine(gpu_factory=lambda: FakeGpu(), cpu_factory=FakeCpu)
        assert eng.supports_partials is True  # take starts on mains

        state["battery"] = True  # unplugged while speaking
        assert eng.transcribe_partial(AUDIO) == "p"  # previews: still the GPU
        assert eng.active_backend == "gpu"
        assert eng.transcribe(AUDIO).text == "cpu"  # the final honours it
        assert eng.cpu_reason == "battery"
