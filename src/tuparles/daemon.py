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

from tuparles import (
    cue,
    history,
    privacy_policy,
    quickchat,
    settings,
    takes,
    telemetry,
)
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
from tuparles.delivery import (
    DeliveryTarget,
    capture_target,
    deliver,
    execute_command,
    to_clipboard,
)
from tuparles.engine import carryover_context, load_engine
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
        self._target = DeliveryTarget()  # window snapshotted when a take starts
        # (class → paste combo + newline mode; id → origin-window paste, #13/#14)
        self._last_edit: Command | None = None  # last delete, for "un peu plus"
        self._entry_source = "hotkey"  # how the current take was started (telemetry)
        self._last_partial = ""  # most recent partial shown — forensics for an
        # empty final decode ("partials showed text, then Rien entendu"; #10)
        self._finishing = False  # a take is being stopped/decoded off the GUI
        # thread; blocks re-entry from any of the three stop entry points so a
        # second press can't race the teardown (#10 freeze fix)
        self._last_delivered = ""  # last delivered text + when, for onset
        self._last_delivered_t = 0.0  # context-carryover into the next take (#18)

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
        if self._finishing:
            return  # a take is being stopped/decoded; ignore until it lands so
            # a fast second press can't race the off-GUI teardown (#10)
        if self._recorder.recording:
            self._press_started_take = False
            self._finishing = True
            self._stop_partials.set()
            # stop() drains/closes the PortAudio stream and once stalled 65 s
            # (id 162). It used to run HERE on the GUI thread → whole-UI freeze.
            # Now the stop AND the decode run on the worker; the GUI thread only
            # flips state and returns, so the bubble stays live through a stall
            # (#10). The _finishing guard above serializes re-entry.
            self._bubble.start_processing()
            self._bridge.state.emit("processing")
            threading.Thread(target=self._stop_and_finish, daemon=True).start()
        else:
            self._press_started_take = True
            self._last_partial = ""  # fresh take, no preview shown yet (#10)
            # Snapshot the destination window NOW, while it still has focus and
            # gnome-shell is calm — before the bubble shows and (on Wayland)
            # steals focus. Captures class + (X11) window id, so a take can paste
            # back where it was dictated even after focus moves (#13, the queue's
            # keystone). Empty fields fall back to a live read at delivery.
            self._target = capture_target()
            self._recorder.start()
            cue.play_start()  # opt-in soft tick: capture is live, speak now
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
        if not self._recorder.recording or self._finishing:
            return
        self._press_started_take = False
        self._finishing = True  # block re-entry while the stream tears down
        self._stop_partials.set()
        self._bubble.cancel()
        self._bridge.state.emit("idle")
        print("take cancelled (Esc)")

        def _drain() -> None:
            # stop() off the GUI thread — Esc on a long take could stall in the
            # same 65 s PortAudio teardown and freeze the UI otherwise (#10).
            try:
                self._recorder.stop()  # return value dropped on purpose
            finally:
                self._finishing = False

        threading.Thread(target=_drain, daemon=True).start()

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
            # (full-buffer re-decode fell behind ~1 Hz on long takes). The
            # engine owns the length — GPU keeps the long context window, the
            # CPU `base` model wants a short one so its one-language-per-window
            # detection tracks the current language (#3 follow-up). Hot-read so
            # a setting change applies to the next tick, no restart.
            window_s = getattr(self._engine, "partial_window_s", PARTIAL_WINDOW_S)
            audio = self._recorder.snapshot()[-SAMPLE_RATE * window_s :]
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
                    self._last_partial = text  # remember for miss-forensics (#10)
                    self._bridge.partial.emit(text)
            elapsed = time.monotonic() - started
            self._stop_partials.wait(max(0.1, PARTIAL_PERIOD_S - elapsed))

    def _stop_and_finish(self) -> None:
        """Worker entry: drain the recorder (was on the GUI thread, the freeze)
        then decode+deliver. The whole slow path is now off the GUI thread."""
        t_stop = time.monotonic()
        audio = self._recorder.stop()
        stop_s = time.monotonic() - t_stop
        self._finish(audio, stop_s)

    def _finish(self, audio, stop_s: float = 0.0) -> None:
        try:
            # Acquiring the lock can block behind an in-flight partial decode:
            # measure that wait apart from the decode it gates.
            # Onset context-carryover (#18): a take starting soon after the last
            # delivery gets that tail as decode left-context, so the cold-started
            # first words ("on vient" → "rien") and a re-dictation after a delete
            # decode better. Bias-only; GPU-only in practice (qwen ignores it).
            context = carryover_context(
                self._last_delivered,
                time.monotonic() - self._last_delivered_t,
                enabled=bool(settings.get("context_carryover")),
                window_s=float(settings.get("context_carryover_window_s")),
                max_chars=int(settings.get("context_carryover_max_chars")),
            )
            t_lock = time.monotonic()
            with self._engine_lock:
                lock_wait_s = time.monotonic() - t_lock
                t_decode = time.monotonic()
                result = self._engine.transcribe(audio, context)
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
            # Quick-chat (#89): a whole-take trigger expands to canned text, which
            # is then delivered + recorded like any dictation. None → pass through.
            expansion = quickchat.expand_active(text)
            if expansion is not None:
                telemetry.event("quickchat.fired")
                text = expansion
            if text:
                t1 = time.monotonic()
                deliver(
                    text,
                    self._target,
                    before_paste=self._hide_bubble_for_paste if IS_WAYLAND else None,
                )
                deliver_s = time.monotonic() - t1
                # Remember for the next take's onset carryover (#18).
                self._last_delivered = text
                self._last_delivered_t = time.monotonic()
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
                    # Minimize before persist: the verbatim text was just
                    # delivered above; only block-tier PII is stripped from the
                    # stored record (#115). The metric drift from placeholders
                    # is within noise (each masked span ≈ one token).
                    take_id = history.record(
                        privacy_policy.redact_for_storage(text),
                        engine=getattr(
                            self._engine, "engine_name", type(self._engine).__name__
                        ),
                        audio_s=audio_s,
                        decode_s=decode_s,
                        deliver_s=deliver_s,
                        lang=result.language,
                        lang_prob=result.language_prob,
                    )
                    # Dev-only (TUPARLES_DEV): stash the raw audio keyed to this
                    # row so it can be replayed across engines/seeds. No-op for
                    # everyone else; never the redacted text — replay needs the
                    # real acoustics. See takes.py / scripts/replay_takes.py.
                    if take_id is not None:
                        takes.save_take(take_id, audio)
                except Exception:
                    pass  # a lost history row must never cost a delivery
                self._bridge.final.emit(text)
            else:
                # Empty final decode — the "Rien entendu" black hole. It records
                # no history row (and so no id-keyed WAV), so without this the
                # one failure most worth debugging leaves zero trace. Print the
                # forensics (raw decode, what the partials showed, timings) and,
                # in dev mode, stash the audio under misses/ for replay (#10).
                audio_s = audio.size / SAMPLE_RATE
                miss_path = takes.save_miss(audio)
                print(
                    f"miss: {audio_s:.1f}s audio, empty final | "
                    f"raw={result.text!r}, last_partial={self._last_partial!r} | "
                    f"decode {decode_s:.2f}s"
                    + (f" | saved {miss_path}" if miss_path else "")
                )
                if not self._recover_with_partial("Rien entendu"):
                    self._bridge.error.emit("Rien entendu")
        except Exception as exc:  # surface in the bubble, never crash
            if not self._recover_with_partial("Décodage raté"):
                self._bridge.error.emit(str(exc)[:120])
        finally:
            self._finishing = False  # teardown done — re-entry allowed again
            self._bridge.state.emit("idle")

    def _recover_with_partial(self, reason: str) -> bool:
        """Recovery belt (#10): when the final decode is lost — an exception, or
        empty while a partial was visibly painted — salvage the last partial by
        copying it to the clipboard (NEVER auto-paste a provisional; the final
        is the truth and this isn't it) and telling the user it's there. The
        screenshot freeze (id 162) landed fine, so this is a net for true losses
        and crashes, not the freeze fix. Returns True iff a partial was saved."""
        partial = self._last_partial.strip()
        if not partial:
            return False
        try:
            to_clipboard(partial)
        except Exception:
            return False
        print(f"recovery: {reason}; partial copied ({len(partial)} chars)")
        self._bridge.error.emit(f"{reason} — partiel copié (Ctrl+V)")
        return True

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


def _rss_mb() -> float:
    """Current resident memory in MB, for the heartbeat — so the next freeze's
    timeline shows whether we were growing. Best-effort; 0.0 if /proc is absent."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def run() -> None:
    import fcntl
    import os
    from pathlib import Path

    from tuparles.hotkey import HotkeyListener
    from tuparles.tray import Tray
    from tuparles.ui import BubbleGroup

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

    # Wayland: KWin/Mutter ignore client move()/xprop, so the frameless bubble
    # gets centred and can't pin itself. Render via XWayland (where both work
    # again) unless the user has deliberately forced a platform. Cheapest fix
    # that keeps the X11-isms; we still deliver via the Wayland path (ydotool/
    # wl-clipboard) since XDG_SESSION_TYPE stays "wayland".
    if IS_WAYLAND and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        print("Wayland — rendering the bubble via XWayland (QT_QPA_PLATFORM=xcb).")

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)  # the bubble hides, the daemon lives
    if app.platformName() == "wayland":
        # Forced native Wayland (no XWayland / overridden): degrade gracefully —
        # bottom-centre placement and all-desktops stickiness are the
        # compositor's call now (see Bubble._make_sticky). Say so, don't pretend.
        print(
            "Note: native Wayland (Qt platform 'wayland') — the compositor "
            "controls bubble placement; bottom-centre and stickiness may not apply."
        )

    print("Warming up the engine…")
    engine = load_engine()

    recorder = Recorder()
    bridge = Bridge()
    # green=GPU, blue=CPU — a pull source for the ambient engine colour. The
    # ResilientEngine flips to "cpu" only on a sticky session fallback.
    backend_source = lambda: getattr(engine, "active_backend", "gpu")  # noqa: E731
    # A group, not a lone Bubble: "bubble_screen" can mirror on every monitor
    # ("all") or follow one, resolved fresh each take. Single-screen modes light
    # exactly one bubble, so this is identical to before on one monitor.
    bubble = BubbleGroup(
        level_source=lambda: recorder.level,
        view=settings.get("view"),
        backend_source=backend_source,
    )
    controller = Controller(engine, recorder, bubble, bridge)

    bridge.toggled.connect(controller.toggle_from_hotkey)
    bridge.combo_released.connect(controller.on_combo_release)
    bridge.cancelled.connect(controller.cancel)
    bridge.partial.connect(bubble.set_partial)
    bridge.final.connect(bubble.show_final)
    bridge.command.connect(bubble.show_final)  # edit confirmation toast
    bridge.error.connect(bubble.show_error)

    tray = Tray(backend_source=backend_source)
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

    # First launch (or a release that added an axis): point at the personalization
    # walkthrough. The Qt carousel (#80 view) will surface this inline; until then
    # this nudge is the no-Qt path, gated by should_show() so it stops once done.
    from tuparles import onboarding

    if onboarding.should_show():
        print("Première fois ? Personnalise avec : tuparles onboarding")

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

    # Persistent heartbeat: the stall_check above only logs once the GUI thread
    # *resumes*, so a whole-system freeze that ends in a reboot kills us before
    # it ever fires. This beat — from a plain thread, into journald which
    # survives reboots — leaves a timeline: after the next freeze, the last `hb:`
    # line dates when we went silent. gui_lag (now − the GUI thread's last tick)
    # tells the two apart: a big gui_lag with beats still flowing = OUR GUI hung;
    # beats stopping cold until reboot = the whole box froze, not us (#10).
    hb_stop = threading.Event()

    def _heartbeat() -> None:
        boot = time.monotonic()
        while not hb_stop.wait(15.0):
            gui_lag = time.monotonic() - stall_last[0]
            print(
                f"hb: up {time.monotonic() - boot:.0f}s "
                f"rss {_rss_mb():.0f}MB gui_lag {gui_lag:.1f}s"
            )

    threading.Thread(target=_heartbeat, daemon=True).start()
    app.aboutToQuit.connect(hb_stop.set)

    app.exec()
    print("\nÀ la prochaine.")
