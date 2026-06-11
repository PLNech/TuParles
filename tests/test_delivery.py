from tuparles.delivery import (
    PASTE_THRESHOLD_CHARS,
    _is_terminal,
    _should_paste,
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
