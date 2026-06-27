"""The off-GUI stop + re-entry guard + partial recovery belt (#10).

The freeze was `recorder.stop()` blocking the GUI thread (65 s, id 162). The
fix moves stop()+decode to a worker and serializes re-entry with `_finishing`.
These pin that wiring with fakes — no Qt event loop, no real audio, no engine.
"""

from types import SimpleNamespace

import numpy as np

from tuparles import daemon as daemon_mod
from tuparles.daemon import Controller
from tuparles.engine import Transcription


class _Sig:
    """A stand-in for a Qt Signal: records every emit."""

    def __init__(self):
        self.emits = []

    def emit(self, *args):
        self.emits.append(args)


class _Bridge:
    def __init__(self):
        for name in ("partial", "final", "command", "error", "state"):
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


def test_toggle_ignores_press_while_finishing(monkeypatch):
    """A second press during teardown must not race stop() (#10 guard)."""
    rec = _Recorder(recording=True)
    c = _controller(SimpleNamespace(), rec, _Bridge())
    c._finishing = True
    c.toggle()
    assert rec.stop_calls == 0  # guarded — no stop, no worker spawned
    assert rec.start_calls == 0


def test_stop_and_finish_drains_recorder_off_gui(monkeypatch):
    """The worker entry calls recorder.stop() (the slow part) then _finish."""
    rec = _Recorder(recording=True)
    c = _controller(SimpleNamespace(), rec, _Bridge())
    seen = {}
    monkeypatch.setattr(
        c, "_finish", lambda audio, stop_s: seen.update(audio=audio, stop_s=stop_s)
    )
    c._stop_and_finish()
    assert rec.stop_calls == 1
    assert "audio" in seen and seen["stop_s"] >= 0.0


def test_recover_with_partial_copies_to_clipboard(monkeypatch):
    clip = {}
    monkeypatch.setattr(daemon_mod, "to_clipboard", lambda t: clip.update(text=t))
    bridge = _Bridge()
    c = _controller(SimpleNamespace(), _Recorder(), bridge)
    c._last_partial = "  un partiel sauvé  "
    assert c._recover_with_partial("Rien entendu") is True
    assert clip["text"] == "un partiel sauvé"  # stripped, never auto-pasted
    assert bridge.error.emits  # user told where it is
    assert "Ctrl+V" in bridge.error.emits[-1][0]


def test_recover_with_partial_noop_without_partial(monkeypatch):
    called = []
    monkeypatch.setattr(daemon_mod, "to_clipboard", lambda t: called.append(t))
    c = _controller(SimpleNamespace(), _Recorder(), _Bridge())
    c._last_partial = "   "  # nothing painted
    assert c._recover_with_partial("Rien entendu") is False
    assert called == []  # never touches the clipboard with empty text


def test_finish_clears_finishing_flag(monkeypatch):
    """_finishing must reset so the next take isn't blocked forever."""

    class _Eng:
        def transcribe(self, audio, context=None):
            return Transcription("bonjour", language="fr", language_prob=1.0)

    monkeypatch.setattr(daemon_mod, "deliver", lambda *a, **k: None)
    monkeypatch.setattr(daemon_mod.history, "record", lambda *a, **k: None)
    monkeypatch.setattr(daemon_mod.takes, "save_take", lambda *a, **k: None)
    monkeypatch.setattr(daemon_mod, "postprocess", lambda text, **k: text)
    c = _controller(_Eng(), _Recorder(), _Bridge())
    c._finishing = True
    c._finish(np.zeros(16_000, dtype=np.int16))
    assert c._finishing is False


def test_empty_final_with_partial_recovers(monkeypatch):
    """Empty decode while a partial was shown → recovery belt fires, not a bare
    'Rien entendu'."""

    class _Eng:
        def transcribe(self, audio, context=None):
            return Transcription("", language=None)

    clip = {}
    monkeypatch.setattr(daemon_mod, "to_clipboard", lambda t: clip.update(text=t))
    monkeypatch.setattr(daemon_mod.takes, "save_miss", lambda audio: None)
    monkeypatch.setattr(daemon_mod, "postprocess", lambda text, **k: text)
    bridge = _Bridge()
    c = _controller(_Eng(), _Recorder(), bridge)
    c._last_partial = "le partiel visible"
    c._finish(np.zeros(16_000, dtype=np.int16))
    assert clip["text"] == "le partiel visible"
    assert any("partiel copié" in e[0] for e in bridge.error.emits)
