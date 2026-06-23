import subprocess

from tuparles import delivery
from tuparles.delivery import (
    PASTE_THRESHOLD_CHARS,
    _is_terminal,
    _should_paste,
    _type_into_focus,
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
