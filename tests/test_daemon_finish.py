"""The off-GUI stop + re-entry guard + partial recovery belt (#10), and the
decode queue that decouples capture from decode (#14).

The freeze was `recorder.stop()` blocking the GUI thread (65 s, id 162). The
fix moves stop()+decode off the GUI thread; #14 then enqueues the take so the
next one starts immediately while this one decodes. These pin that wiring with
fakes — no Qt event loop, no real audio, no engine.
"""

from types import SimpleNamespace

import numpy as np

from tuparles import daemon as daemon_mod
from tuparles.daemon import Controller, _QueuedTake
from tuparles.delivery import DeliveryTarget
from tuparles.engine import Transcription


def _take(audio=None, target=None, partial="", seq=1):
    return _QueuedTake(
        seq=seq,
        audio=np.zeros(16_000, dtype=np.int16) if audio is None else audio,
        target=target or DeliveryTarget(),
        partial=partial,
    )


class _Sig:
    """A stand-in for a Qt Signal: records every emit."""

    def __init__(self):
        self.emits = []

    def emit(self, *args):
        self.emits.append(args)


class _Bridge:
    def __init__(self):
        for name in (
            "partial",
            "final",
            "command",
            "error",
            "state",
            "queued",
            "delivered",
        ):
            setattr(self, name, _Sig())


class _Recorder:
    def __init__(self, recording=True, audio=None):
        self._recording = recording
        self._audio = np.zeros(16_000, dtype=np.int16) if audio is None else audio
        self.stop_calls = 0
        self.start_calls = 0

    @property
    def recording(self):
        return self._recording

    def stop(self):
        self.stop_calls += 1
        self._recording = False
        return self._audio

    def start(self):
        self.start_calls += 1
        self._recording = True


class _Bubble:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        return lambda *a, **k: self.events.append(name)


def _controller(engine, recorder, bridge):
    return Controller(engine, recorder, _Bubble(), bridge)


def test_toggle_ignores_press_while_stopping(monkeypatch):
    """A second press during teardown must not race stop() (#10 guard)."""
    rec = _Recorder(recording=True)
    c = _controller(SimpleNamespace(), rec, _Bridge())
    c._stopping = True
    c.toggle()
    assert rec.stop_calls == 0  # guarded — no stop, no worker spawned
    assert rec.start_calls == 0


def test_stop_and_enqueue_drains_recorder_and_queues(monkeypatch):
    """The worker entry calls recorder.stop() (the slow part), enqueues a take
    carrying its target+partial, frees the recorder, and bumps pending (#14)."""
    rec = _Recorder(recording=True)
    bridge = _Bridge()
    c = _controller(SimpleNamespace(), rec, bridge)
    c._stopping = True
    tgt = DeliveryTarget(wm_class="code", window_id="42")
    c._stop_and_enqueue(tgt, "un partiel")
    assert rec.stop_calls == 1
    assert c._stopping is False  # recorder freed → next take may start
    assert c._pending == 1
    take = c._decode_q.get_nowait()
    assert take.target == tgt and take.partial == "un partiel" and take.seq == 1
    assert bridge.queued.emits == [(1,)]  # mini-bubble notified (#15)


def test_enqueue_records_mode(monkeypatch):
    """The take carries how it ended (hold vs toggle) for the journal."""
    c = _controller(SimpleNamespace(), _Recorder(recording=True), _Bridge())
    c._stop_and_enqueue(DeliveryTarget(), "", "hold")
    assert c._decode_q.get_nowait().mode == "hold"


def test_combo_release_marks_hold_then_stops(monkeypatch):
    """A push-to-talk release flags the stop as 'hold' and the enqueued take
    inherits it; a plain toggle stays 'toggle'."""
    from tuparles.config import HOTKEY_HOLD_S

    rec = _Recorder(recording=True)
    c = _controller(SimpleNamespace(), rec, _Bridge())
    captured = {}
    monkeypatch.setattr(
        c,
        "_stop_and_enqueue",
        lambda target, partial, mode="toggle": captured.update(mode=mode),
    )

    # Run the spawned worker inline so the assert isn't racing the thread.
    class _Inline:
        def __init__(self, target, args=(), daemon=False):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)

    monkeypatch.setattr(daemon_mod.threading, "Thread", _Inline)
    c._press_started_take = True
    c.on_combo_release(HOTKEY_HOLD_S + 0.1)  # held long enough → release ends it
    assert captured["mode"] == "hold"
    assert c._ending_via_hold is False  # consumed, not left armed for the next


def test_depth_cap_refuses_new_take_with_toast(monkeypatch):
    """At the queue depth cap a new take is refused with a toast, never a silent
    drop and never another audio buffer piled on (#14)."""
    monkeypatch.setattr(
        daemon_mod.settings, "get", lambda k: 2 if k == "queue_depth_cap" else None
    )
    rec = _Recorder(recording=False)
    bridge = _Bridge()
    c = _controller(SimpleNamespace(), rec, bridge)
    c._pending = 2  # at cap
    c.toggle()
    assert rec.start_calls == 0  # no new recording started
    assert any("File pleine" in e[0] for e in bridge.error.emits)


def test_recover_with_partial_copies_to_clipboard(monkeypatch):
    clip = {}
    monkeypatch.setattr(daemon_mod, "to_clipboard", lambda t: clip.update(text=t))
    bridge = _Bridge()
    c = _controller(SimpleNamespace(), _Recorder(), bridge)
    assert c._recover_with_partial("Rien entendu", "  un partiel sauvé  ") is True
    assert clip["text"] == "un partiel sauvé"  # stripped, never auto-pasted
    assert bridge.error.emits  # user told where it is
    assert "Ctrl+V" in bridge.error.emits[-1][0]


def test_recover_with_partial_noop_without_partial(monkeypatch):
    called = []
    monkeypatch.setattr(daemon_mod, "to_clipboard", lambda t: called.append(t))
    c = _controller(SimpleNamespace(), _Recorder(), _Bridge())
    assert c._recover_with_partial("Rien entendu", "   ") is False
    assert called == []  # never touches the clipboard with empty text


def test_finish_decrements_pending_and_signals_delivered(monkeypatch):
    """_finish must release its pending slot and emit `delivered` so the next
    take isn't blocked at the cap and the mini-bubble clears (#14/#15)."""

    class _Eng:
        def transcribe(self, audio, context=None):
            return Transcription("bonjour", language="fr", language_prob=1.0)

    monkeypatch.setattr(daemon_mod, "deliver", lambda *a, **k: None)
    monkeypatch.setattr(daemon_mod.history, "record", lambda *a, **k: None)
    monkeypatch.setattr(daemon_mod.takes, "save_take", lambda *a, **k: None)
    monkeypatch.setattr(daemon_mod, "postprocess", lambda text, **k: text)
    bridge = _Bridge()
    c = _controller(_Eng(), _Recorder(recording=False), bridge)
    c._pending = 1
    c._finish(_take(seq=7))
    assert c._pending == 0
    assert bridge.delivered.emits == [(7,)]


def test_empty_final_with_partial_recovers(monkeypatch):
    """Empty decode while a partial was shown → recovery belt fires, not a bare
    'Rien entendu'. The partial comes from the take, not live controller state."""

    class _Eng:
        def transcribe(self, audio, context=None):
            return Transcription("", language=None)

    clip = {}
    monkeypatch.setattr(daemon_mod, "to_clipboard", lambda t: clip.update(text=t))
    monkeypatch.setattr(daemon_mod.takes, "save_miss", lambda audio: None)
    monkeypatch.setattr(daemon_mod, "postprocess", lambda text, **k: text)
    bridge = _Bridge()
    c = _controller(_Eng(), _Recorder(recording=False), bridge)
    c._finish(_take(partial="le partiel visible"))
    assert clip["text"] == "le partiel visible"
    assert any("partiel copié" in e[0] for e in bridge.error.emits)


# ── origin-window delivery routing (#14) ────────────────────────────────────


def _deliver_controller(monkeypatch, *, deliver_to="origin", wayland=False):
    """A controller wired so _deliver's side effects are observable: the
    delivered (text, target) and the focus dance (activate calls)."""
    calls = {"delivered": [], "activated": []}
    monkeypatch.setattr(daemon_mod, "IS_WAYLAND", wayland)
    monkeypatch.setattr(
        daemon_mod.settings,
        "get",
        lambda k: deliver_to if k == "deliver_to" else None,
    )
    monkeypatch.setattr(
        daemon_mod,
        "deliver",
        lambda text, target, **k: calls["delivered"].append((text, target)),
    )
    monkeypatch.setattr(daemon_mod, "current_window_id", lambda: "here-7")
    monkeypatch.setattr(
        daemon_mod,
        "activate_window",
        lambda wid: calls["activated"].append(wid) or True,
    )
    c = _controller(SimpleNamespace(), _Recorder(recording=False), _Bridge())
    return c, calls


def test_deliver_origin_refocuses_when_focus_moved(monkeypatch):
    """Overlap: focus moved off the dictation window → refocus origin, paste,
    hand focus back where the user is now."""
    c, calls = _deliver_controller(monkeypatch, deliver_to="origin")
    c._deliver("salut", DeliveryTarget(wm_class="code", window_id="orig-1"))
    assert calls["activated"] == ["orig-1", "here-7"]  # to origin, then back
    assert calls["delivered"] == [("salut", DeliveryTarget("code", "orig-1"))]


def test_deliver_origin_skips_dance_without_overlap(monkeypatch):
    """No overlap (still focused on the dictation window) → plain paste, no
    focus dance at all."""
    c, calls = _deliver_controller(monkeypatch, deliver_to="origin")
    monkeypatch.setattr(daemon_mod, "current_window_id", lambda: "orig-1")
    c._deliver("salut", DeliveryTarget(wm_class="code", window_id="orig-1"))
    assert calls["activated"] == []  # focus never touched
    assert calls["delivered"] == [("salut", DeliveryTarget("code", "orig-1"))]


def test_deliver_current_mode_never_refocuses(monkeypatch):
    """deliver_to=current keeps the pre-queue behaviour: paste in place."""
    c, calls = _deliver_controller(monkeypatch, deliver_to="current")
    c._deliver("salut", DeliveryTarget(wm_class="code", window_id="orig-1"))
    assert calls["activated"] == []
    assert calls["delivered"] == [("salut", DeliveryTarget("code", "orig-1"))]


def test_deliver_wayland_uses_bubble_hide_not_refocus(monkeypatch):
    """Wayland can't refocus by id: keep the bubble-hide path, no activate."""
    c, calls = _deliver_controller(monkeypatch, deliver_to="origin", wayland=True)
    c._deliver("salut", DeliveryTarget(wm_class="code", window_id="orig-1"))
    assert calls["activated"] == []
    assert calls["delivered"] == [("salut", DeliveryTarget("code", "orig-1"))]
