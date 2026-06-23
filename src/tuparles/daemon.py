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
import sys
import threading
import time

from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from tuparles import history, settings, telemetry
from tuparles.audio import Recorder
from tuparles.commands import Command
from tuparles.commands import parse as parse_command
from tuparles.config import (
    HOTKEY_HOLD_S,
    IS_WAYLAND,
    PARTIAL_MIN_AUDIO_S,
    PARTIAL_PERIOD_S,
    PARTIAL_WINDOW_S,
    SAMPLE_RATE,
)
from tuparles.delivery import capture_focus_class, deliver, execute_command
from tuparles.engine import load_engine
from tuparles.pipeline import postprocess


class Bridge(QObject):
    """Thread-safe funnel: emitted anywhere, delivered on the GUI thread."""

    toggled = Signal()
    combo_released = Signal(float)  # hotkey combo let go after N seconds
    cancelled = Signal()  # Esc — abort an in-flight take
    partial = Signal(str)
    final = Signal(str)
    command = Signal(str)  # a voice edit ran — short label for the toast
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
        self._press_started_take = False  # hold-to-talk: release only stops
        # a recording the same press started, never an ongoing toggled take
        self._target_focus = ""  # window class captured when a take starts;
        # delivery pastes Ctrl+Shift+V vs Ctrl+V from this (see capture below)
        self._last_edit: Command | None = None  # last delete, for "un peu plus"
        self._entry_source = "hotkey"  # how the current take was started (telemetry)

    @Slot()
    def toggle_from_hotkey(self) -> None:
        self._entry_source = "hotkey"
        self.toggle()

    @Slot()
    def toggle_from_tray(self) -> None:
        self._entry_source = "tray"
        self.toggle()

    @Slot()
    def toggle(self) -> None:
        if self._recorder.recording:
            self._press_started_take = False
            self._stop_partials.set()
            # stop() drains and closes the PortAudio stream on the GUI thread —
            # if it ever blocks, the whole UI freezes here, before any decode.
            # Time it so a freeze accuses the right step instead of "decode".
            t_stop = time.monotonic()
            audio = self._recorder.stop()
            stop_s = time.monotonic() - t_stop
            self._bubble.start_processing()
            self._bridge.state.emit("processing")
            threading.Thread(
                target=self._finish, args=(audio, stop_s), daemon=True
            ).start()
        else:
            self._press_started_take = True
            # Wayland only: read focus NOW, while the target window still has
            # it and gnome-shell is calm — before the bubble shows and steals
            # it. A delivery-time read raced that and missed terminals (~12 ms,
            # GUI ok). X11 keeps its live delivery-time read (the bubble never
            # steals focus there, so it stays accurate and pastes where focus
            # actually is, not merely where the take began).
            self._target_focus = capture_focus_class() if IS_WAYLAND else ""
            self._recorder.start()
            telemetry.event("entry.dictation", source=self._entry_source)
            self._bubble.start_recording()
            self._bridge.state.emit("recording")
            if getattr(self._engine, "supports_partials", False):
                self._stop_partials.clear()
                threading.Thread(target=self._partials_loop, daemon=True).start()

    @Slot()
    def cancel(self) -> None:
        """Esc: abort the current take. Stop the recorder and DISCARD its
        audio — no decode, no delivery, nothing recorded. No-op when idle so
        a global Esc never does anything except dismiss a live take."""
        if not self._recorder.recording:
            return
        self._press_started_take = False
        self._stop_partials.set()
        self._recorder.stop()  # return value dropped on purpose
        self._bubble.cancel()
        self._bridge.state.emit("idle")
        print("take cancelled (Esc)")

    @Slot(float)
    def on_combo_release(self, held_s: float) -> None:
        """Hold-to-talk: combo held past the threshold → release ends the take.
        A short tap leaves the recording running (toggle mode)."""
        if (
            held_s >= HOTKEY_HOLD_S
            and self._recorder.recording
            and self._press_started_take
        ):
            self.toggle()

    def _hide_bubble_for_paste(self) -> None:
        """Wayland only: the bubble steals keyboard focus (Mutter ignores the
        no-focus hints X11 honours), so a ydotool paste fired while it's up
        lands in the bubble, not the user's window. Hide it first — focus
        returns to the target — and the final-text emit re-shows it after.
        Called from the delivery worker thread, so the hide is marshalled onto
        the GUI thread and blocks until done before the keystroke fires."""
        QMetaObject.invokeMethod(
            self._bubble, "hide", Qt.ConnectionType.BlockingQueuedConnection
        )

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
                    # Cap what reaches the UI: a hallucination loop can emit
                    # thousands of chars and text layout is O(length) per
                    # frame. The bubble shows ~600 chars at most anyway.
                    if len(text) > 800:
                        text = "…" + text[-800:]
                    self._bridge.partial.emit(text)
            elapsed = time.monotonic() - started
            self._stop_partials.wait(max(0.1, PARTIAL_PERIOD_S - elapsed))

    def _finish(self, audio, stop_s: float = 0.0) -> None:
        try:
            # Acquiring the lock can block behind an in-flight partial decode:
            # measure that wait apart from the decode it gates.
            t_lock = time.monotonic()
            with self._engine_lock:
                lock_wait_s = time.monotonic() - t_lock
                t_decode = time.monotonic()
                result = self._engine.transcribe(audio)
                decode_s = time.monotonic() - t_decode
            t_post = time.monotonic()
            text = postprocess(
                result.text,
                on_syntax_fire=lambda name: telemetry.event("syntax.used", name=name),
            )
            post_s = time.monotonic() - t_post
            # Command layer: a take is EITHER an edit command or text, never
            # both. A literal-escape ('dis "efface"') unwraps back to text.
            cmd = parse_command(text)
            if cmd is not None and cmd.action == "literal":
                text, cmd = cmd.text, None
            if cmd is not None:
                self._run_command(cmd)
                return  # an edit is not a transcript — no delivery, no history
            if text:
                t1 = time.monotonic()
                deliver(
                    text,
                    self._target_focus,
                    before_paste=self._hide_bubble_for_paste if IS_WAYLAND else None,
                )
                deliver_s = time.monotonic() - t1
                audio_s = audio.size / SAMPLE_RATE
                # Full per-step breakdown: stop (GUI thread) + lock-wait +
                # decode + post-process + deliver. The dominant term names
                # the freeze; total ≈ perceived stop→paste latency.
                print(
                    f"take: {audio_s:.0f}s audio, {len(text)} chars, "
                    f"lang={result.language} | stop {stop_s:.2f}s, "
                    f"lock {lock_wait_s:.2f}s, decode {decode_s:.2f}s, "
                    f"post {post_s:.2f}s, deliver {deliver_s:.2f}s"
                )
                try:
                    history.record(
                        text,
                        engine=getattr(
                            self._engine, "engine_name", type(self._engine).__name__
                        ),
                        audio_s=audio_s,
                        decode_s=decode_s,
                        deliver_s=deliver_s,
                        lang=result.language,
                        lang_prob=result.language_prob,
                    )
                except Exception:
                    pass  # a lost history row must never cost a delivery
                self._bridge.final.emit(text)
            else:
                self._bridge.error.emit("Rien entendu")
        except Exception as exc:  # surface in the bubble, never crash
            self._bridge.error.emit(str(exc)[:120])
        finally:
            self._bridge.state.emit("idle")

    def _resolve_nudge(self, cmd: Command) -> Command | None:
        """'un peu plus' = one more unit of the last edit; 'un peu moins' = undo
        one step. No prior edit → None (nothing to nudge)."""
        if self._last_edit is None:
            return None
        if cmd.direction == "more":
            return Command("delete", unit=self._last_edit.unit, count=1)
        return Command("undo")

    def _run_command(self, cmd: Command) -> None:
        """Execute a voice edit on the focused window. Runs on the decode
        worker thread (like deliver), so the Wayland bubble-hide is marshalled
        to the GUI thread first — otherwise the keystroke lands in the focus-
        stealing bubble, not the user's window (see _hide_bubble_for_paste)."""
        telemetry.event("command.fired", name=cmd.action)
        if cmd.action == "nudge":
            resolved = self._resolve_nudge(cmd)
            if resolved is None:
                self._bridge.command.emit("rien à ajuster")
                return
            cmd = resolved
        if IS_WAYLAND:
            self._hide_bubble_for_paste()
        label = execute_command(cmd)
        # Remember the last destructive edit so a later "un peu plus" can chain;
        # an undo clears it (there's nothing left to extend).
        self._last_edit = cmd if cmd.action == "delete" else None
        self._bridge.command.emit(label)


def run() -> None:
    import fcntl
    import os
    from pathlib import Path

    from tuparles.hotkey import HotkeyListener
    from tuparles.tray import Tray
    from tuparles.ui import Bubble

    # GNOME launches us with stdout piped to journald, which Python block-
    # buffers: the forensic prints below never flushed during the freeze
    # hunts. Line-buffer explicitly so the journal sees them as they happen.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]  # always a TextIO here

    # Single instance: two daemons mean two hotkey listeners — every take
    # double-toggles and double-delivers. The flock dies with the process,
    # so a crashed daemon never wedges the next launch.
    # Held open for the whole process lifetime on purpose: closing it releases
    # the flock and defeats the single-instance guard. Not a leak.
    lock_file = open(  # noqa: SIM115
        Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tuparles.lock", "w"
    )
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("TuParles tourne déjà — cette instance s'efface.")
        return

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)  # the bubble hides, the daemon lives

    print("Warming up the engine…")
    engine = load_engine()

    recorder = Recorder()
    bridge = Bridge()
    bubble = Bubble(level_source=lambda: recorder.level, view=settings.get("view"))
    controller = Controller(engine, recorder, bubble, bridge)

    bridge.toggled.connect(controller.toggle_from_hotkey)
    bridge.combo_released.connect(controller.on_combo_release)
    bridge.cancelled.connect(controller.cancel)
    bridge.partial.connect(bubble.set_partial)
    bridge.final.connect(bubble.show_final)
    bridge.command.connect(bubble.show_final)  # edit confirmation toast
    bridge.error.connect(bubble.show_error)

    tray = Tray()
    bridge.state.connect(tray.set_state)
    bridge.final.connect(tray.on_final)
    tray.toggle_requested.connect(controller.toggle_from_tray)
    tray.view_changed.connect(bubble.set_view)
    tray.quit_requested.connect(app.quit)

    def _restart() -> None:
        """Become a fresh daemon in place. execv swaps the process image,
        so the instance flock (CLOEXEC) releases exactly when the new self
        takes over — no window for a double daemon or an orphaned one."""
        if recorder.recording:
            return  # never drop an in-flight take; stop dictating first
        print("Redémarrage…")
        os.execv(sys.argv[0], sys.argv)

    tray.restart_requested.connect(_restart)

    listener = HotkeyListener(
        on_toggle=bridge.toggled.emit,
        on_combo_release=bridge.combo_released.emit,
        on_cancel=bridge.cancelled.emit,
    )
    listener.start()
    app.aboutToQuit.connect(listener.stop)
    print("TuParles daemon up — Right Ctrl + Right Alt to dictate. Ctrl-C quits.")

    # Qt's loop won't run Python signal handlers unless the interpreter gets
    # scheduled; the no-op timer keeps Ctrl-C responsive.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    waker = QTimer()
    waker.start(200)
    waker.timeout.connect(lambda: None)

    # GUI-stall watchdog: a heartbeat that arrives late means the main
    # thread was blocked — exactly the "UI frozen" reports. One journal
    # line per stall turns the next one from a guess into a measurement.
    stall_last = [time.monotonic()]

    def _stall_check() -> None:
        now = time.monotonic()
        gap = now - stall_last[0]
        if gap > 1.0:
            print(f"GUI stall: main thread blocked ~{gap:.1f}s")
        stall_last[0] = now

    watchdog = QTimer()
    watchdog.timeout.connect(_stall_check)
    watchdog.start(250)

    app.exec()
    print("\nÀ la prochaine.")
