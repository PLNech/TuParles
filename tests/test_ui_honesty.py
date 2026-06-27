"""UI honesty + capture cues (#27, #28): the bubble never red-recants a salvaged
partial (it dissolves an amber 'recovered' state instead), and a long decode
shows an elapsed counter so it reads as working, not frozen.

Pure helpers tested without Qt; the bubble state/colour tested offscreen
(skipped where Qt is absent), with an injected clock so no test ever sleeps."""

import pytest


def _qt(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])


class TestDecodeCounterText:
    """Pure: '' until the decode runs past the threshold, then '(Ns)'."""

    def test_under_threshold_is_blank(self):
        pytest.importorskip("PySide6")  # ui.py imports Qt at module load
        from tuparles.ui import decode_counter_text

        assert decode_counter_text(0.0) == ""
        assert decode_counter_text(2.9) == ""

    def test_at_and_past_threshold_counts_whole_seconds(self):
        pytest.importorskip("PySide6")  # ui.py imports Qt at module load
        from tuparles.ui import DECODE_COUNTER_AFTER_S, decode_counter_text

        assert decode_counter_text(DECODE_COUNTER_AFTER_S) == "(3s)"
        assert decode_counter_text(12.7) == "(12s)"  # truncates, doesn't round up


class TestRecoveredState:
    """The never-recant salvage: amber, not the red error flip, and it keeps the
    partial's words on screen."""

    def _bubble(self, tmp_path, monkeypatch, clock=None):
        _qt(tmp_path, monkeypatch)
        from tuparles.ui import Bubble

        return Bubble(level_source=lambda: 0.0, clock=clock or (lambda: 0.0))

    def test_recovered_shows_partial_in_amber(self, tmp_path, monkeypatch):
        pytest.importorskip("PySide6")  # ui.py imports Qt at module load
        from tuparles.ui import _AMBER, _ERR

        b = self._bubble(tmp_path, monkeypatch)
        b.show_recovered("un partiel sauvé")
        assert b._state == "recovered"
        assert b._text == "un partiel sauvé"  # the words stay — never recant
        assert b._bar_color() == _AMBER  # held, not the red of a failure
        assert b._bar_color() != _ERR

    def test_recovered_defers_to_a_live_recording(self, tmp_path, monkeypatch):
        b = self._bubble(tmp_path, monkeypatch)
        b.start_recording()
        b.show_recovered("trop tard")  # a next take already grabbed the bubble
        assert b._state == "recording"
        assert b._text != "trop tard"

    def test_recovered_badge_is_ctrl_v(self, tmp_path, monkeypatch):
        b = self._bubble(tmp_path, monkeypatch)
        b.show_recovered("salut")
        badge = b._badge()
        assert badge is not None and badge[0] == "Ctrl+V"


class TestProcessingCounter:
    """The elapsed counter only runs during a decode and resets when it ends."""

    def _bubble(self, tmp_path, monkeypatch, clock):
        _qt(tmp_path, monkeypatch)
        from tuparles.ui import Bubble

        return Bubble(level_source=lambda: 0.0, clock=clock)

    def test_no_badge_before_threshold(self, tmp_path, monkeypatch):
        now = [100.0]
        b = self._bubble(tmp_path, monkeypatch, clock=lambda: now[0])
        b.start_processing()
        now[0] += 1.0  # only 1s in
        assert b._badge() is None

    def test_badge_appears_on_a_long_decode(self, tmp_path, monkeypatch):
        now = [100.0]
        b = self._bubble(tmp_path, monkeypatch, clock=lambda: now[0])
        b.start_processing()
        now[0] += 8.0
        badge = b._badge()
        assert badge is not None and badge[0] == "(8s)"

    def test_counter_resets_when_decode_ends(self, tmp_path, monkeypatch):
        now = [100.0]
        b = self._bubble(tmp_path, monkeypatch, clock=lambda: now[0])
        b.start_processing()
        now[0] += 8.0
        b.show_final("done")  # leaving processing clears the stamp
        assert b._processing_since is None
        assert b._badge() is None
