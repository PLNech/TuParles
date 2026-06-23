import subprocess

from tuparles import delivery
from tuparles.delivery import (
    MAX_CHUNK_CHARS,
    PASTE_THRESHOLD_CHARS,
    _chunk_for_paste,
    _focus_is_terminal,
    _focus_wm_class,
    _is_terminal,
    _should_chunk,
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

    SAMPLES = [
        "",
        "one short line",
        "a\nb\nc",
        "para one.\n\npara two, a bit longer but still small.",
        "word " * 200,                      # long, spaces to break on
        "x" * (MAX_CHUNK_CHARS * 3 + 7),    # long, NO break → hard cuts
        "Phrase une. Phrase deux! Phrase trois? Et fin." * 20,
        "trailing newline\n",
        "\nleading newline",
        "é" * (MAX_CHUNK_CHARS + 50),       # non-ASCII, still split by length
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


class TestChunkedDelivery:
    """Long/multi-line text is pasted in pieces so an editor can't fold it into
    "[Pasted text]" before you reread it — still paste-only, full text left on
    the clipboard as the manual-paste backup."""

    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr(delivery.time, "sleep", lambda _s: None)

    def test_x11_long_text_pastes_in_pieces_never_types(self, monkeypatch):
        self._no_sleep(monkeypatch)
        monkeypatch.setattr(delivery, "_WAYLAND", False)
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
        delivery.deliver(text, focus_class="firefox|Navigator")

        assert not typed                      # never typed, even chunked
        assert len(keys) >= 2                 # several paste keystrokes
        assert set(keys) == {"ctrl+v"}        # firefox → plain Ctrl+V
        assert clips[-1] == text              # full text restored last

    def test_wayland_chunked_hides_bubble_once_then_pastes_pieces(self, monkeypatch):
        self._no_sleep(monkeypatch)
        monkeypatch.setattr(delivery, "_WAYLAND", True)
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
            text, focus_class="firefox|Navigator",
            before_paste=lambda: hides.append(1),
        )

        assert hides == [1]                   # bubble hidden exactly once
        assert len(keys) >= 2                 # several paste keystrokes
        assert set(keys) == {"ctrl+v"}        # firefox → plain Ctrl+V
