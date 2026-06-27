"""Queue chips (#15): the small strip that shows takes still decoding in the
FIFO queue (#14) and flashes each as it lands. Pure colour decision tested
without Qt; the widget model tested offscreen (skipped where Qt is absent)."""

import pytest


def _qt(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])


class TestChipColor:
    """Decoding = the live backend hue; delivered = the same hue brightened (so
    green never stops meaning GPU). No Qt app needed — QColor stands alone."""

    def test_decoding_is_the_base_hue(self):
        pytest.importorskip("PySide6")
        from PySide6.QtGui import QColor

        from tuparles.ui import chip_color

        base = QColor(122, 199, 130)
        assert chip_color("decoding", base) == base

    def test_delivered_is_brighter_same_hue(self):
        pytest.importorskip("PySide6")
        from PySide6.QtGui import QColor

        from tuparles.ui import chip_color

        base = QColor(122, 199, 130)
        out = chip_color("delivered", base)
        # brighter on every channel, never darker (lerp toward white)
        assert out.red() >= base.red()
        assert out.green() >= base.green()
        assert out.blue() >= base.blue()
        assert (out.red(), out.green(), out.blue()) != (
            base.red(),
            base.green(),
            base.blue(),
        )

    def test_unknown_state_reads_as_decoding(self):
        pytest.importorskip("PySide6")
        from PySide6.QtGui import QColor

        from tuparles.ui import chip_color

        base = QColor(10, 20, 30)
        assert chip_color("whatever", base) == base


class TestQueueChipsModel:
    def _chips(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles.ui import QueueChips

        return QueueChips()

    def test_queued_adds_a_decoding_chip(self, tmp_path, monkeypatch):
        chips = self._chips(tmp_path, monkeypatch)
        chips.on_queued(1)
        assert chips._chips == [[1, "decoding"]]

    def test_queued_is_idempotent(self, tmp_path, monkeypatch):
        chips = self._chips(tmp_path, monkeypatch)
        chips.on_queued(1)
        chips.on_queued(1)  # a duplicate signal must not double-add
        assert chips._chips == [[1, "decoding"]]

    def test_chips_keep_arrival_order(self, tmp_path, monkeypatch):
        chips = self._chips(tmp_path, monkeypatch)
        for seq in (3, 1, 2):
            chips.on_queued(seq)
        assert [c[0] for c in chips._chips] == [3, 1, 2]

    def test_delivered_flashes_then_removable(self, tmp_path, monkeypatch):
        chips = self._chips(tmp_path, monkeypatch)
        chips.on_queued(1)
        chips.on_queued(2)
        chips.on_delivered(1)
        assert [c[1] for c in chips._chips if c[0] == 1] == ["delivered"]
        # the deferred removal (timer-driven in the app) drops just that chip
        chips._remove(1)
        assert [c[0] for c in chips._chips] == [2]

    def test_empty_hides_strip(self, tmp_path, monkeypatch):
        chips = self._chips(tmp_path, monkeypatch)
        chips.on_queued(1)
        chips._remove(1)
        assert chips._chips == []
        assert not chips.isVisible()

    def test_disabled_setting_adds_nothing(self, tmp_path, monkeypatch):
        chips = self._chips(tmp_path, monkeypatch)
        from tuparles import settings

        settings.put("queue_chips", False)
        chips.on_queued(1)
        assert chips._chips == []

    def test_width_grows_with_chip_count(self, tmp_path, monkeypatch):
        chips = self._chips(tmp_path, monkeypatch)
        chips.on_queued(1)
        one = chips._content_width()
        chips.on_queued(2)
        assert chips._content_width() > one
