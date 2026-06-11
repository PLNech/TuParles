"""The daemon: hotkey → record (live partials in the bubble) → final decode
→ punctuate → deliver into the focused window.

Threading map — Qt owns the main thread, everything else marshals in:
  pynput thread        → Bridge.toggled (queued)  → Controller.toggle (GUI)
  partials thread      → Bridge.partial (queued)  → Bubble.set_partial (GUI)
  final-decode thread  → Bridge.final / .error    → Bubble + deliver
A single engine lock serializes GPU calls so an in-flight partial can
never race the final beam decode.
"""

import signal
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from tuparles import history
from tuparles.audio import Recorder
from tuparles.config import (
    PARTIAL_MIN_AUDIO_S,
    PARTIAL_PERIOD_S,
    PARTIAL_WINDOW_S,
    SAMPLE_RATE,
)
from tuparles.delivery import deliver
from tuparles.engine import load_engine
from tuparles.lexicon import apply_lexicon
from tuparles.punctuation import apply_spoken_punctuation


class Bridge(QObject):
    """Thread-safe funnel: emitted anywhere, delivered on the GUI thread."""

    toggled = Signal()
    partial = Signal(str)
    final = Signal(str)
    error = Signal(str)
    state = Signal(str)  # idle | recording | processing — tray glyph follows


class Controller(QObject):
    """Owns recorder + engine + worker threads. Slots run on the GUI thread."""

    def __init__(self, engine, recorder: Recorder, bubble, bridge: Bridge) -> None:
        super().__init__()
        self._engine = engine
        self._bubble = bubble
        self._bridge = bridge
        self._recorder = recorder
        self._engine_lock = threading.Lock()  # partials vs final decode
        self._stop_partials = threading.Event()

    @Slot()
    def toggle(self) -> None:
        if self._recorder.recording:
            self._stop_partials.set()
            audio = self._recorder.stop()
            self._bubble.start_processing()
            self._bridge.state.emit("processing")
            threading.Thread(
                target=self._finish, args=(audio,), daemon=True
            ).start()
        else:
            self._recorder.start()
            self._bubble.start_recording()
            self._bridge.state.emit("recording")
            if getattr(self._engine, "supports_partials", False):
                self._stop_partials.clear()
                threading.Thread(target=self._partials_loop, daemon=True).start()

    def _partials_loop(self) -> None:
        """~1 Hz greedy re-decode of the whole growing buffer (≤1 s on GPU)."""
        while not self._stop_partials.is_set():
            started = time.monotonic()
            # Tail window only: the bubble elides left so older audio is
            # invisible anyway, and a bounded window bounds decode latency
            # (full-buffer re-decode fell behind ~1 Hz on long takes).
            audio = self._recorder.snapshot()[-SAMPLE_RATE * PARTIAL_WINDOW_S :]
            if audio.size >= SAMPLE_RATE * PARTIAL_MIN_AUDIO_S:
                with self._engine_lock:
                    if self._stop_partials.is_set():
                        return
                    try:
                        text = self._engine.transcribe_partial(audio)
                    except Exception:
                        text = ""  # a dropped partial is invisible; final decode rules
                if text and not self._stop_partials.is_set():
                    self._bridge.partial.emit(text)
            elapsed = time.monotonic() - started
            self._stop_partials.wait(max(0.1, PARTIAL_PERIOD_S - elapsed))

    def _finish(self, audio) -> None:
        try:
            with self._engine_lock:
                raw = self._engine.transcribe(audio)
            text = apply_lexicon(apply_spoken_punctuation(raw))
            if text:
                deliver(text)
                try:
                    history.record(text, engine=type(self._engine).__name__)
                except Exception:
                    pass  # a lost history row must never cost a delivery
                self._bridge.final.emit(text)
            else:
                self._bridge.error.emit("Rien entendu")
        except Exception as exc:  # surface in the bubble, never crash
            self._bridge.error.emit(str(exc)[:120])
        finally:
            self._bridge.state.emit("idle")


def run() -> None:
    from tuparles.hotkey import HotkeyListener
    from tuparles.tray import Tray
    from tuparles.ui import Bubble

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)  # the bubble hides, the daemon lives

    print("Warming up the engine…")
    engine = load_engine()

    recorder = Recorder()
    bridge = Bridge()
    bubble = Bubble(level_source=lambda: recorder.level)
    controller = Controller(engine, recorder, bubble, bridge)

    bridge.toggled.connect(controller.toggle)
    bridge.partial.connect(bubble.set_partial)
    bridge.final.connect(bubble.show_final)
    bridge.error.connect(bubble.show_error)

    tray = Tray()
    bridge.state.connect(tray.set_state)
    bridge.final.connect(tray.on_final)
    tray.toggle_requested.connect(controller.toggle)
    tray.quit_requested.connect(app.quit)

    listener = HotkeyListener(on_toggle=bridge.toggled.emit)
    listener.start()
    app.aboutToQuit.connect(listener.stop)
    print("TuParles daemon up — Right Ctrl + Right Alt to dictate. Ctrl-C quits.")

    # Qt's loop won't run Python signal handlers unless the interpreter gets
    # scheduled; the no-op timer keeps Ctrl-C responsive.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    waker = QTimer()
    waker.start(200)
    waker.timeout.connect(lambda: None)

    app.exec()
    print("\nÀ la prochaine.")
