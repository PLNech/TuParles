import subprocess

from tuparles import delivery
from tuparles.delivery import (
    PASTE_THRESHOLD_CHARS,
    _focus_is_terminal,
    _focus_wm_class,
    _is_terminal,
    _should_paste,
    _type_into_focus,
    _wayland_paste,
    capture_focus_class,
)


class TestTerminalDetection:
    def test_known_terminals(self):
        assert _is_terminal("gnome-terminal-server")
        assert _is_terminal("Alacritty")
        assert _is_terminal(" kitty\n")

    def test_regular_apps(self):
        assert not _is_terminal("firefox")
        assert not _is_terminal("slack")
        assert not _is_terminal("")


class TestThreshold:
    def test_threshold_is_sane(self):
        # ~2 s of typing at 10 ms/char: anything longer should paste.
        assert 100 <= PASTE_THRESHOLD_CHARS <= 500


class TestShouldPaste:
    def test_short_ascii_types(self):
        assert not _should_paste("plain english, fits everywhere")

    def test_long_text_pastes(self):
        assert _should_paste("x" * (PASTE_THRESHOLD_CHARS + 1))

    def test_accents_paste_even_short(self):
        # é/à missing from a QWERTY layout → xdotool would remap the keymap
        # per char, MappingNotify storm, whole-desktop freeze. Never type it.
        assert _should_paste("c'était à peine enregistré")

    def test_curly_apostrophe_pastes(self):
        assert _should_paste("I’m switching to English")

    def test_newlines_are_typable(self):
        assert not _should_paste("line one\nline two")


class TestNoTypeFallback:
    """A paste-destined text must never be typed — not even if the paste
    keystroke errors. Typing it would corrupt + freeze (the 3-min bug)."""

    def _record_calls(self, monkeypatch, paste_raises=False):
        calls = []

        # These assert the X11 xdotool path; pin it so the suite is valid on
        # a Wayland dev machine too (where _type_into_focus would otherwise
        # take the ydotool branch).
        monkeypatch.setattr(delivery, "_WAYLAND", False)

        def fake_run(argv, *a, **kw):
            calls.append(argv)
            if paste_raises and argv[:2] == ["xdotool", "key"]:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout", 0))
            return subprocess.CompletedProcess(argv, 0, stdout="firefox\n")

        monkeypatch.setattr(delivery.subprocess, "run", fake_run)
        return calls

    def test_long_text_pastes_never_types(self, monkeypatch):
        calls = self._record_calls(monkeypatch)
        _type_into_focus("é" + "x" * PASTE_THRESHOLD_CHARS)
        assert not any(c[:2] == ["xdotool", "type"] for c in calls)
        assert ["xdotool", "key", "ctrl+v"] in calls

    def test_paste_keystroke_failure_still_no_type(self, monkeypatch):
        # The exact 3-min-freeze trigger: ctrl+v lands but xdotool blocks on
        # a saturated X server and times out. Must NOT re-type the text.
        calls = self._record_calls(monkeypatch, paste_raises=True)
        _type_into_focus("été " * 100)
        assert not any(c[:2] == ["xdotool", "type"] for c in calls)

    def test_short_ascii_still_types(self, monkeypatch):
        calls = self._record_calls(monkeypatch)
        _type_into_focus("just type this")
        assert any(c[:2] == ["xdotool", "type"] for c in calls)


class TestWaylandFocusClass:
    """Parsing the GNOME focus-window extension's gdbus reply, and picking
    the paste combo from it."""

    def _fake_gdbus(self, monkeypatch, stdout="", returncode=0, raises=None):
        def fake_run(argv, *a, **kw):
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(argv, returncode, stdout=stdout)

        monkeypatch.setattr(delivery.subprocess, "run", fake_run)

    def test_parses_gvariant_tuple(self, monkeypatch):
        self._fake_gdbus(
            monkeypatch, stdout="('Gnome-terminal|gnome-terminal-server',)\n"
        )
        assert _focus_wm_class() == "Gnome-terminal|gnome-terminal-server"

    def test_empty_when_service_missing(self, monkeypatch):
        # gdbus exits non-zero when the name isn't on the bus.
        self._fake_gdbus(monkeypatch, stdout="Error: ...\n", returncode=1)
        assert _focus_wm_class() == ""

    def test_empty_when_gdbus_absent(self, monkeypatch):
        self._fake_gdbus(monkeypatch, raises=FileNotFoundError("gdbus"))
        assert _focus_wm_class() == ""

    def test_terminal_matched_on_instance_half(self, monkeypatch):
        # gnome-terminal carries the token in the instance, not the class.
        self._fake_gdbus(
            monkeypatch, stdout="('Gnome-terminal|gnome-terminal-server',)\n"
        )
        assert _focus_is_terminal()

    def test_regular_app_not_terminal(self, monkeypatch):
        self._fake_gdbus(monkeypatch, stdout="('firefox|Navigator',)\n")
        assert not _focus_is_terminal()

    def test_no_extension_treated_as_app(self, monkeypatch):
        self._fake_gdbus(monkeypatch, returncode=1)
        assert not _focus_is_terminal()


class TestWaylandPasteCombo:
    """_wayland_paste sends Ctrl+Shift+V into terminals, Ctrl+V elsewhere."""

    def _capture(self, monkeypatch, is_terminal):
        calls = []
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(delivery, "_focus_is_terminal", lambda: is_terminal)
        monkeypatch.setattr(
            delivery.subprocess, "run",
            lambda argv, *a, **kw: calls.append(argv)
            or subprocess.CompletedProcess(argv, 0),
        )
        return calls

    def test_terminal_gets_ctrl_shift_v(self, monkeypatch):
        calls = self._capture(monkeypatch, is_terminal=True)
        _wayland_paste()
        assert calls == [["ydotool", "key", "--delay", "200", "ctrl+shift+v"]]

    def test_app_gets_ctrl_v(self, monkeypatch):
        calls = self._capture(monkeypatch, is_terminal=False)
        _wayland_paste()
        assert calls == [["ydotool", "key", "--delay", "200", "ctrl+v"]]

    def test_no_ydotool_no_keystroke(self, monkeypatch):
        calls = []
        monkeypatch.setattr(delivery.shutil, "which", lambda _: None)
        monkeypatch.setattr(
            delivery.subprocess, "run",
            lambda *a, **kw: calls.append(a) or subprocess.CompletedProcess([], 0),
        )
        _wayland_paste()
        assert calls == []

    def test_paste_failure_does_not_raise(self, monkeypatch):
        # Clipboard is the net: a ydotool timeout must not propagate, or
        # deliver() would mark a good take failed and skip history.
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(delivery, "_focus_is_terminal", lambda: False)

        def boom(argv, *a, **kw):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout", 0))

        monkeypatch.setattr(delivery.subprocess, "run", boom)
        _wayland_paste()  # must not raise


class TestWaylandClipboard:
    def test_wayland_without_wl_copy_does_not_use_xsel(self, monkeypatch):
        calls = []
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: None)
        monkeypatch.setattr(
            delivery.subprocess, "run",
            lambda argv, *a, **kw: calls.append(argv)
            or subprocess.CompletedProcess(argv, 0),
        )
        delivery.to_clipboard("hello")
        # No xsel fallback: it writes the XWayland clipboard ydotool can't read.
        assert calls == []

    def test_wayland_uses_wl_copy(self, monkeypatch):
        calls = []
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/wl-copy")
        monkeypatch.setattr(
            delivery.subprocess, "run",
            lambda argv, *a, **kw: calls.append(argv)
            or subprocess.CompletedProcess(argv, 0),
        )
        delivery.to_clipboard("hello")
        assert calls == [["wl-copy"]]


class TestCapturedFocus:
    """A window class captured at take-start is used for the paste combo
    instead of a (race-prone) delivery-time read."""

    def test_capture_reads_extension_with_short_timeout(self, monkeypatch):
        # Wayland-only and capped short — it runs on the GUI thread at start.
        seen = {}
        monkeypatch.setattr(
            delivery, "_focus_wm_class",
            lambda timeout=2.0: seen.update(timeout=timeout)
            or "Gnome-terminal|gnome-terminal-server",
        )
        assert capture_focus_class() == "Gnome-terminal|gnome-terminal-server"
        assert seen["timeout"] <= 1.0  # must not block the GUI thread for 2 s

    def test_captured_terminal_picks_shift_combo_without_live_read(
        self, monkeypatch
    ):
        # A captured terminal class must drive the combo on its own; a live
        # _focus_is_terminal() call here would mean the race wasn't bypassed.
        calls = []
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(
            delivery, "_focus_is_terminal",
            lambda: (_ for _ in ()).throw(AssertionError("live read not bypassed")),
        )
        monkeypatch.setattr(
            delivery.subprocess, "run",
            lambda argv, *a, **kw: calls.append(argv)
            or subprocess.CompletedProcess(argv, 0),
        )
        _wayland_paste(focus_class="Gnome-terminal|gnome-terminal-server")
        assert calls == [["ydotool", "key", "--delay", "200", "ctrl+shift+v"]]

    def test_empty_capture_falls_back_to_live_read(self, monkeypatch):
        calls = []
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(delivery, "_focus_is_terminal", lambda: True)
        monkeypatch.setattr(
            delivery.subprocess, "run",
            lambda argv, *a, **kw: calls.append(argv)
            or subprocess.CompletedProcess(argv, 0),
        )
        _wayland_paste(focus_class="")  # no capture → live read decides
        assert calls == [["ydotool", "key", "--delay", "200", "ctrl+shift+v"]]


class TestBeforePasteHook:
    """before_paste (the daemon hides the focus-stealing bubble there) must
    run BEFORE the ydotool keystroke, or the paste lands in the bubble."""

    def test_hook_runs_before_keystroke(self, monkeypatch):
        events = []
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(delivery, "_focus_is_terminal", lambda: True)
        monkeypatch.setattr(
            delivery.subprocess, "run",
            lambda argv, *a, **kw: events.append(("ydotool", argv[-1]))
            or subprocess.CompletedProcess(argv, 0),
        )
        _wayland_paste(focus_class="", before_paste=lambda: events.append(("hide",)))
        assert events == [("hide",), ("ydotool", "ctrl+shift+v")]

    def test_hook_skipped_when_ydotool_absent(self, monkeypatch):
        # No ydotool → no keystroke and no pointless bubble hide/flicker.
        events = []
        monkeypatch.setattr(delivery.shutil, "which", lambda _: None)
        _wayland_paste(focus_class="", before_paste=lambda: events.append("hide"))
        assert events == []

    def test_deliver_threads_hook_to_wayland_paste(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        monkeypatch.setattr(delivery, "to_clipboard", lambda t: None)
        monkeypatch.setattr(
            delivery, "_wayland_paste",
            lambda fc="", bp=None: seen.update(focus=fc, hook=bp),
        )
        def hook():
            pass

        delivery.deliver("hi", "Alacritty|Alacritty", before_paste=hook)
        assert seen == {"focus": "Alacritty|Alacritty", "hook": hook}
