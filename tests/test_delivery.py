import subprocess
from typing import ClassVar

from tuparles import delivery
from tuparles.delivery import (
    MAX_CHUNK_CHARS,
    PASTE_THRESHOLD_CHARS,
    _chunk_for_paste,
    _focus_is_terminal,
    _focus_wm_class,
    _is_terminal,
    _paste_chunks,
    _should_chunk,
    _should_paste,
    _type_into_focus,
    _wayland_paste,
    capture_focus_class,
    resolve_newline_mode,
)


class TestNewlineMode:
    """Target-aware newlines (#5): a pasted lone LF is eaten by submit-on-Enter
    inputs, so they get a Shift+Enter keystroke instead."""

    def test_auto_is_lf_for_editor_or_terminal(self, monkeypatch):
        monkeypatch.setattr(delivery.settings, "get", lambda k: "auto")
        assert resolve_newline_mode("gnome-terminal") == "lf"
        assert resolve_newline_mode("code") == "lf"
        assert resolve_newline_mode("") == "lf"

    def test_auto_upgrades_known_chat_apps(self, monkeypatch):
        monkeypatch.setattr(delivery.settings, "get", lambda k: "auto")
        assert resolve_newline_mode("Slack|slack") == "shift-enter"
        assert resolve_newline_mode("discord") == "shift-enter"

    def test_explicit_setting_forces_mode(self, monkeypatch):
        monkeypatch.setattr(delivery.settings, "get", lambda k: "shift-enter")
        assert resolve_newline_mode("gnome-terminal") == "shift-enter"
        monkeypatch.setattr(delivery.settings, "get", lambda k: "lf")
        assert resolve_newline_mode("slack") == "lf"

    def _capture(self, monkeypatch):
        sent: list[str] = []
        clips: list[str] = []
        monkeypatch.setattr(delivery, "to_clipboard", lambda t: clips.append(t))
        monkeypatch.setattr(delivery.time, "sleep", lambda *_: None)
        return sent, clips

    def test_shift_enter_sends_keystroke_not_lf_paste(self, monkeypatch):
        sent, clips = self._capture(monkeypatch)
        _paste_chunks("a\nb", "ctrl+v", sent.append, newline_mode="shift-enter")
        assert "shift+Return" in sent  # the newline went as a keystroke
        assert "\n" not in clips  # never put a lone LF on the clipboard

    def test_lf_mode_pastes_literal_newline(self, monkeypatch):
        sent, clips = self._capture(monkeypatch)
        _paste_chunks("a\nb", "ctrl+v", sent.append, newline_mode="lf")
        assert "shift+Return" not in sent and "Return" not in sent
        assert "\n" in clips  # literal LF pasted, as before


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


class TestShouldChunk:
    def test_short_single_line_is_not_chunked(self):
        # The common case: a sentence pastes in one shot, unchanged.
        assert not _should_chunk("juste une phrase courte, rien de spécial")

    def test_long_text_is_chunked(self):
        assert _should_chunk("x" * (MAX_CHUNK_CHARS + 1))

    def test_multiline_is_chunked_even_when_short(self):
        # An editor collapses ANY multi-line paste into "[Pasted text]",
        # length aside — so two short lines still paste progressively.
        assert _should_chunk("ligne une\nligne deux")


class TestChunkForPaste:
    """Progressive-paste splitter: paragraph-first, rejoins byte-for-byte,
    no text piece carries a newline, each piece within the cap."""

    SAMPLES: ClassVar[list[str]] = [
        "",
        "one short line",
        "a\nb\nc",
        "para one.\n\npara two, a bit longer but still small.",
        "word " * 200,  # long, spaces to break on
        "x" * (MAX_CHUNK_CHARS * 3 + 7),  # long, NO break → hard cuts
        "Phrase une. Phrase deux! Phrase trois? Et fin." * 20,
        "trailing newline\n",
        "\nleading newline",
        "é" * (MAX_CHUNK_CHARS + 50),  # non-ASCII, still split by length
    ]

    def test_rejoins_to_the_original_exactly(self):
        for s in self.SAMPLES:
            assert "".join(_chunk_for_paste(s)) == s, repr(s)

    def test_no_text_piece_contains_a_newline(self):
        # Newlines are emitted as their own one-char pieces; a text piece with
        # an embedded newline would itself trip the multi-line collapse.
        for s in self.SAMPLES:
            for piece in _chunk_for_paste(s):
                assert piece == "\n" or "\n" not in piece, repr(piece)

    def test_pieces_within_the_cap(self):
        for s in self.SAMPLES:
            for piece in _chunk_for_paste(s):
                assert len(piece) <= MAX_CHUNK_CHARS, repr(piece)

    def test_short_text_is_one_piece(self):
        assert _chunk_for_paste("a single short line") == ["a single short line"]

    def test_newline_becomes_its_own_piece(self):
        assert _chunk_for_paste("a\nb") == ["a", "\n", "b"]

    def test_blank_line_preserved_as_two_newline_pieces(self):
        assert _chunk_for_paste("a\n\nb") == ["a", "\n", "\n", "b"]

    def test_long_paragraph_breaks_after_a_sentence_end(self):
        # Two sentences just over the cap should split at the sentence
        # boundary, not mid-word.
        first = "Première phrase qui occupe de la place. "
        second = "x" * MAX_CHUNK_CHARS
        chunks = _chunk_for_paste(first + second)
        assert chunks[0] == first  # broke right after ". "


class TestNoTypeFallback:
    """On X11 nothing is ever typed while a clipboard tool exists — not even
    short ASCII, not even if the paste keystroke errors. `xdotool type` remaps
    the keymap (MappingNotify storm → gnome-shell re-grab → desktop freeze), so
    the clipboard + Ctrl+V is the only injection path (the 3-min bug)."""

    def _record_calls(self, monkeypatch, paste_raises=False, has_xsel=True):
        calls = []

        # These assert the X11 xdotool path; pin it so the suite is valid on
        # a Wayland dev machine too (where _type_into_focus would otherwise
        # take the ydotool branch). Pin xsel presence too so the paste-vs-type
        # branch is deterministic regardless of what's installed on the runner.
        monkeypatch.setattr(delivery, "_WAYLAND", False)
        monkeypatch.setattr(
            delivery.shutil,
            "which",
            lambda name: f"/usr/bin/{name}" if has_xsel else None,
        )

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

    def test_short_ascii_now_pastes_not_types(self, monkeypatch):
        # The fix: even a short pure-ASCII take pastes rather than types, so a
        # dictation session never drips MappingNotify into gnome-shell.
        calls = self._record_calls(monkeypatch)
        _type_into_focus("just type this")
        assert not any(c[:2] == ["xdotool", "type"] for c in calls)
        assert ["xdotool", "key", "ctrl+v"] in calls

    def test_no_xsel_does_not_type_by_default(self, monkeypatch):
        # New default (this app froze GNOME once by typing): with no xsel, the
        # text is left on the clipboard with a loud notify — NOT typed.
        monkeypatch.delenv("TUPARLES_ALLOW_TYPE_FALLBACK", raising=False)
        calls = self._record_calls(monkeypatch, has_xsel=False)
        _type_into_focus("just type this")
        assert not any(c[:2] == ["xdotool", "type"] for c in calls)

    def test_no_xsel_types_only_with_opt_in_env(self, monkeypatch):
        # Explicit opt-in: TUPARLES_ALLOW_TYPE_FALLBACK=1 restores typing for a
        # box where a lost take is judged worse than a transient churn.
        monkeypatch.setenv("TUPARLES_ALLOW_TYPE_FALLBACK", "1")
        calls = self._record_calls(monkeypatch, has_xsel=False)
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
        # Pin the daemon-less (0.1.8) argv shape these asserts expect; the modern
        # evdev path has its own coverage (TestYdotoolArgv). Without this the
        # result depends on whether ydotoold is installed on the dev box.
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", False)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(delivery, "_focus_is_terminal", lambda: is_terminal)
        monkeypatch.setattr(
            delivery.subprocess,
            "run",
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
            delivery.subprocess,
            "run",
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


class TestYdotoolArgv:
    """_ydotool_key_argv emits the syntax the host's ydotool understands:
    daemon-less 0.1.8 takes a chord string (`ctrl+v`); modern ≥1.0 takes
    <keycode>:<state> evdev pairs (press in order, release in reverse)."""

    def test_legacy_emits_chord_string_with_delay(self, monkeypatch):
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", False)
        assert delivery._ydotool_key_argv("ctrl+v") == [
            "ydotool",
            "key",
            "--delay",
            "200",
            "ctrl+v",
        ]

    def test_modern_emits_evdev_press_release_pairs(self, monkeypatch):
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", True)
        # ctrl=29, v=47: press in order, release in reverse — a real chord.
        assert delivery._ydotool_key_argv("ctrl+v") == [
            "ydotool",
            "key",
            "29:1",
            "47:1",
            "47:0",
            "29:0",
        ]

    def test_modern_chord_three_keys(self, monkeypatch):
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", True)
        # ctrl=29, shift=42, v=47
        assert delivery._ydotool_key_argv("ctrl+shift+v") == [
            "ydotool",
            "key",
            "29:1",
            "42:1",
            "47:1",
            "47:0",
            "42:0",
            "29:0",
        ]


class TestWaylandClipboard:
    def test_wayland_without_wl_copy_does_not_use_xsel(self, monkeypatch):
        calls = []
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: None)
        monkeypatch.setattr(
            delivery.subprocess,
            "run",
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
            delivery.subprocess,
            "run",
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
            delivery,
            "_focus_wm_class",
            lambda timeout=2.0: seen.update(timeout=timeout)
            or "Gnome-terminal|gnome-terminal-server",
        )
        assert capture_focus_class() == "Gnome-terminal|gnome-terminal-server"
        assert seen["timeout"] <= 1.0  # must not block the GUI thread for 2 s

    def test_captured_terminal_picks_shift_combo_without_live_read(self, monkeypatch):
        # A captured terminal class must drive the combo on its own; a live
        # _focus_is_terminal() call here would mean the race wasn't bypassed.
        calls = []
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", False)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(
            delivery,
            "_focus_is_terminal",
            lambda: (_ for _ in ()).throw(AssertionError("live read not bypassed")),
        )
        monkeypatch.setattr(
            delivery.subprocess,
            "run",
            lambda argv, *a, **kw: calls.append(argv)
            or subprocess.CompletedProcess(argv, 0),
        )
        _wayland_paste(focus_class="Gnome-terminal|gnome-terminal-server")
        assert calls == [["ydotool", "key", "--delay", "200", "ctrl+shift+v"]]

    def test_empty_capture_falls_back_to_live_read(self, monkeypatch):
        calls = []
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", False)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(delivery, "_focus_is_terminal", lambda: True)
        monkeypatch.setattr(
            delivery.subprocess,
            "run",
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
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", False)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        monkeypatch.setattr(delivery, "_focus_is_terminal", lambda: True)
        monkeypatch.setattr(
            delivery.subprocess,
            "run",
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
            delivery,
            "_wayland_paste",
            lambda fc="", bp=None: seen.update(focus=fc, hook=bp),
        )

        def hook():
            pass

        delivery.deliver("hi", "Alacritty|Alacritty", before_paste=hook)
        assert seen == {"focus": "Alacritty|Alacritty", "hook": hook}


class TestChunkedDelivery:
    """Long/multi-line text is pasted in pieces so an editor can't fold it into
    "[Pasted text]" before you reread it — still paste-only, full text left on
    the clipboard as the manual-paste backup."""

    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr(delivery.time, "sleep", lambda _s: None)

    def test_x11_long_text_pastes_in_pieces_never_types(self, monkeypatch):
        self._no_sleep(monkeypatch)
        monkeypatch.setattr(delivery, "_WAYLAND", False)
        monkeypatch.setattr(delivery.shutil, "which", lambda name: f"/usr/bin/{name}")
        clips, keys, typed = [], [], []

        def fake_run(argv, *a, **kw):
            if argv[:1] == ["xsel"]:
                clips.append(kw.get("input", b"").decode())
            elif argv[:2] == ["xdotool", "key"]:
                keys.append(argv[2])
            elif argv[:2] == ["xdotool", "type"]:
                typed.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="firefox\n")

        monkeypatch.setattr(delivery.subprocess, "run", fake_run)

        text = "Première phrase. " + "mot " * 200  # > cap, multi-piece
        delivery.deliver(text, target="firefox|Navigator")

        assert not typed  # never typed, even chunked
        assert len(keys) >= 2  # several paste keystrokes
        assert set(keys) == {"ctrl+v"}  # firefox → plain Ctrl+V
        assert clips[-1] == text  # full text restored last

    def test_wayland_chunked_hides_bubble_once_then_pastes_pieces(self, monkeypatch):
        self._no_sleep(monkeypatch)
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        monkeypatch.setattr(delivery, "_YDOTOOL_MODERN", False)
        monkeypatch.setattr(delivery.shutil, "which", lambda _: "/usr/bin/ydotool")
        hides, keys = [], []

        def fake_run(argv, *a, **kw):
            if argv[:2] == ["ydotool", "key"]:
                keys.append(argv[-1])
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(delivery.subprocess, "run", fake_run)
        monkeypatch.setattr(delivery, "to_clipboard", lambda _t: None)

        text = "ligne une\n" + "x" * (MAX_CHUNK_CHARS + 5)  # multi-line + long
        delivery.deliver(
            text,
            target="firefox|Navigator",
            before_paste=lambda: hides.append(1),
        )

        assert hides == [1]  # bubble hidden exactly once
        assert len(keys) >= 2  # several paste keystrokes
        assert set(keys) == {"ctrl+v"}  # firefox → plain Ctrl+V


class TestCaptureTarget:
    """DeliveryTarget snapshot at take-start (#13): class + (X11) window id."""

    def test_x11_captures_class_and_id(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", False)

        def fake_run(argv, *a, **kw):
            if argv == ["xdotool", "getactivewindow"]:
                return subprocess.CompletedProcess(argv, 0, stdout="12345\n")
            if argv[:2] == ["xprop", "-id"]:
                # The reliable path: xdotool 3.x has no getwindowclassname.
                return subprocess.CompletedProcess(
                    argv, 0, stdout='WM_CLASS(STRING) = "alacritty", "Alacritty"\n'
                )
            return subprocess.CompletedProcess(argv, 0, stdout="")

        monkeypatch.setattr(delivery.subprocess, "run", fake_run)
        t = delivery.capture_target()
        assert t.window_id == "12345" and t.wm_class == "alacritty|Alacritty"

    def test_x11_capture_failure_is_empty(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", False)

        def boom(*a, **k):
            raise OSError("no xdotool")

        monkeypatch.setattr(delivery.subprocess, "run", boom)
        t = delivery.capture_target()
        assert t.window_id == "" and t.wm_class == ""

    def test_wayland_captures_class_only(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        monkeypatch.setattr(
            delivery, "_focus_wm_class", lambda timeout=0.5: "Slack|slack"
        )
        t = delivery.capture_target()
        assert t.wm_class == "Slack|slack" and t.window_id == ""

    def test_deliver_accepts_target_object(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(delivery, "to_clipboard", lambda _t: None)
        monkeypatch.setattr(
            delivery,
            "_type_into_focus",
            lambda text, fc="", bp=None: seen.update(fc=fc),
        )
        delivery.deliver("hi", delivery.DeliveryTarget(wm_class="kitty", window_id="9"))
        assert seen["fc"] == "kitty"


class TestOriginFocus:
    """X11 refocus-by-id helpers for origin-window delivery (#14)."""

    def test_current_window_id_reads_active(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", False)
        monkeypatch.setattr(
            delivery.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess([], 0, stdout="98765\n"),
        )
        assert delivery.current_window_id() == "98765"

    def test_current_window_id_empty_on_wayland(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        assert delivery.current_window_id() == ""

    def test_activate_window_calls_xdotool_sync(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", False)
        calls = []
        monkeypatch.setattr(
            delivery.subprocess,
            "run",
            lambda argv, *a, **k: calls.append(argv)
            or subprocess.CompletedProcess(argv, 0),
        )
        assert delivery.activate_window("42") is True
        assert calls == [["xdotool", "windowactivate", "--sync", "42"]]

    def test_activate_window_noop_without_id(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", False)
        called = []
        monkeypatch.setattr(
            delivery.subprocess, "run", lambda *a, **k: called.append(a)
        )
        assert delivery.activate_window("") is False
        assert called == []

    def test_activate_window_false_on_wayland(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", True)
        assert delivery.activate_window("42") is False


class TestWmClass:
    """Cross-version window class via xprop (xdotool 3.x lacks
    getwindowclassname → the silent 'everything pastes Ctrl+V' bug)."""

    def _xprop(self, monkeypatch, stdout="", raises=None):
        def fake_run(argv, *a, **kw):
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(argv, 0, stdout=stdout)

        monkeypatch.setattr(delivery.subprocess, "run", fake_run)

    def test_parses_both_halves(self, monkeypatch):
        self._xprop(monkeypatch, stdout='WM_CLASS(STRING) = "kitty", "kitty"\n')
        assert delivery._x11_wm_class("42") == "kitty|kitty"

    def test_distinct_instance_and_class(self, monkeypatch):
        self._xprop(
            monkeypatch,
            stdout='WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"\n',
        )
        out = delivery._x11_wm_class("42")
        assert out == "gnome-terminal-server|Gnome-terminal"
        assert delivery._pair_is_terminal(out)  # the whole point: now detected

    def test_empty_without_id(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            delivery.subprocess, "run", lambda *a, **k: called.append(a)
        )
        assert delivery._x11_wm_class("") == ""
        assert called == []  # no id → no xprop call

    def test_empty_when_xprop_absent(self, monkeypatch):
        self._xprop(monkeypatch, raises=FileNotFoundError("xprop"))
        assert delivery._x11_wm_class("42") == ""

    def test_empty_on_unset_property(self, monkeypatch):
        self._xprop(monkeypatch, stdout="WM_CLASS:  not found.\n")
        assert delivery._x11_wm_class("42") == ""


class TestExecuteCommand:
    """Voice edits send the right keystrokes and NEVER type text. Backend is
    X11 here (dev machine); _send_key dispatches to xdotool, captured below."""

    def _record(self, monkeypatch):
        monkeypatch.setattr(delivery, "_WAYLAND", False)
        keys = []
        monkeypatch.setattr(delivery, "_send_key", keys.append)
        return keys

    def test_delete_word_count(self, monkeypatch):
        from tuparles.commands import Command

        keys = self._record(monkeypatch)
        label = delivery.execute_command(Command("delete", "word", 3))
        assert keys == ["ctrl+BackSpace"] * 3
        assert "3 mots" in label

    def test_delete_one_word_singular_label(self, monkeypatch):
        from tuparles.commands import Command

        keys = self._record(monkeypatch)
        label = delivery.execute_command(Command("delete", "word", 1))
        assert keys == ["ctrl+BackSpace"]
        assert label == "1 mot effacé"

    def test_delete_chars(self, monkeypatch):
        from tuparles.commands import Command

        keys = self._record(monkeypatch)
        delivery.execute_command(Command("delete", "char", 4))
        assert keys == ["BackSpace"] * 4

    def test_delete_all(self, monkeypatch):
        from tuparles.commands import Command

        keys = self._record(monkeypatch)
        label = delivery.execute_command(Command("delete", "all", 1))
        assert keys == ["ctrl+a", "BackSpace"]
        assert label == "tout effacé"

    def test_delete_line(self, monkeypatch):
        from tuparles.commands import Command

        keys = self._record(monkeypatch)
        delivery.execute_command(Command("delete", "line", 1))
        assert keys == ["shift+Home", "BackSpace"]

    def test_undo(self, monkeypatch):
        from tuparles.commands import Command

        keys = self._record(monkeypatch)
        label = delivery.execute_command(Command("undo"))
        assert keys == ["ctrl+z"]
        assert label == "annulé"

    def test_open_terminal_spawns_first_available(self, monkeypatch):
        from tuparles.commands import Command

        self._record(monkeypatch)
        monkeypatch.setattr(
            delivery.shutil,
            "which",
            lambda name: "/usr/bin/kgx" if name == "kgx" else None,
        )
        spawned = []
        monkeypatch.setattr(
            delivery.subprocess,
            "Popen",
            lambda argv, **kw: spawned.append(argv) or None,
        )
        label = delivery.execute_command(Command("open_terminal"))
        assert spawned == [["kgx"]]
        assert label == "terminal ouvert"

    def test_open_terminal_none_available(self, monkeypatch):
        from tuparles.commands import Command

        self._record(monkeypatch)
        monkeypatch.setattr(delivery.shutil, "which", lambda _name: None)
        label = delivery.execute_command(Command("open_terminal"))
        assert label == "terminal indisponible"


class TestIsTextClipboard:
    """Type-aware guard (#28): only plain text is safe to snapshot+restore.
    Anything richer (image, files, app data) must bail so we never destroy it
    by writing a text-only value back."""

    def test_plain_text_targets_are_ok(self):
        assert delivery.is_text_clipboard(["UTF8_STRING", "STRING", "TARGETS"])
        assert delivery.is_text_clipboard(["text/plain;charset=utf-8"])

    def test_html_alongside_plain_text_is_still_text(self):
        # Rich text — restoring UTF8 loses formatting, but it's still text, not a
        # binary payload; acceptable.
        assert delivery.is_text_clipboard(["text/html", "text/plain", "UTF8_STRING"])

    def test_image_is_not_text(self):
        assert not delivery.is_text_clipboard(["image/png", "image/bmp", "TARGETS"])

    def test_image_with_a_text_target_is_still_rejected(self):
        # An image that also offers a text representation: a text-only restore
        # would drop the image. Bail — leave the clipboard alone.
        assert not delivery.is_text_clipboard(["text/plain", "image/png"])

    def test_file_list_is_not_text(self):
        # text/uri-list is a FILE list — its "text/" prefix must not fool us.
        assert not delivery.is_text_clipboard(
            ["text/uri-list", "x-special/gnome-copied-files"]
        )

    def test_unknown_or_meta_only_is_not_text(self):
        assert not delivery.is_text_clipboard(None)
        assert not delivery.is_text_clipboard([])
        assert not delivery.is_text_clipboard(["TARGETS", "TIMESTAMP", "MULTIPLE"])


class TestClipboardRestore:
    """deliver() preserves the user's clipboard around a paste — but only when
    asked AND it's safely text. The pasted text always lands first; the restore
    (if any) follows after the settle."""

    def _wire(self, monkeypatch, *, restore_setting, snapshot):
        settings_map = {"newline_mode": "auto", "clipboard_restore": restore_setting}
        monkeypatch.setattr(delivery.settings, "get", lambda k: settings_map.get(k))
        clips: list[str] = []
        monkeypatch.setattr(delivery, "to_clipboard", lambda t: clips.append(t))
        monkeypatch.setattr(delivery, "from_clipboard", lambda: snapshot)
        monkeypatch.setattr(delivery, "_type_into_focus", lambda *a, **k: None)
        monkeypatch.setattr(delivery.time, "sleep", lambda *_: None)
        return clips

    def test_restores_old_text_after_paste(self, monkeypatch):
        clips = self._wire(monkeypatch, restore_setting=True, snapshot="OLD")
        delivery.deliver("dictée", "code")
        assert clips == ["dictée", "OLD"]  # paste lands, then the old text returns

    def test_skips_restore_when_not_text(self, monkeypatch):
        # from_clipboard() returns None for an image/files/unknown payload — we
        # leave our pasted text rather than nuke what we can't faithfully hold.
        clips = self._wire(monkeypatch, restore_setting=True, snapshot=None)
        delivery.deliver("dictée", "code")
        assert clips == ["dictée"]

    def test_no_snapshot_when_disabled(self, monkeypatch):
        called: list[bool] = []
        settings_map = {"newline_mode": "auto", "clipboard_restore": False}
        monkeypatch.setattr(delivery.settings, "get", lambda k: settings_map.get(k))
        monkeypatch.setattr(delivery, "from_clipboard", lambda: called.append(True))
        monkeypatch.setattr(delivery, "to_clipboard", lambda t: None)
        monkeypatch.setattr(delivery, "_type_into_focus", lambda *a, **k: None)
        delivery.deliver("dictée", "code")
        assert called == []  # setting off → the clipboard is never even read

    def test_restore_failure_never_fails_the_take(self, monkeypatch):
        # The take is already delivered; a xsel hiccup on the restore write must
        # be swallowed (logged), NOT propagate out of deliver() as a take error.
        settings_map = {"newline_mode": "auto", "clipboard_restore": True}
        monkeypatch.setattr(delivery.settings, "get", lambda k: settings_map.get(k))
        monkeypatch.setattr(delivery, "from_clipboard", lambda: "OLD")
        monkeypatch.setattr(delivery, "_type_into_focus", lambda *a, **k: None)
        monkeypatch.setattr(delivery.time, "sleep", lambda *_: None)
        calls: list[str] = []

        def flaky(text):
            calls.append(text)
            if text == "OLD":  # the restore write is the one that fails
                raise subprocess.TimeoutExpired(["xsel"], 10)

        monkeypatch.setattr(delivery, "to_clipboard", flaky)
        delivery.deliver("dictée", "code")  # must not raise
        assert calls == ["dictée", "OLD"]  # paste set, restore attempted + swallowed

    def test_initial_set_failure_aborts_loudly(self, monkeypatch):
        # The paste depends on the initial clipboard set; if THAT raises, the
        # take must fail loudly (propagate) so the daemon's recovery belt fires.
        settings_map = {"newline_mode": "auto", "clipboard_restore": False}
        monkeypatch.setattr(delivery.settings, "get", lambda k: settings_map.get(k))

        def boom(_text):
            raise subprocess.CalledProcessError(1, ["xsel"])

        monkeypatch.setattr(delivery, "to_clipboard", boom)
        monkeypatch.setattr(delivery, "_type_into_focus", lambda *a, **k: None)
        import pytest

        with pytest.raises(subprocess.CalledProcessError):
            delivery.deliver("dictée", "code")
