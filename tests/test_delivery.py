from tuparles.delivery import PASTE_THRESHOLD_CHARS, _is_terminal


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
