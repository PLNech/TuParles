"""The tray glyph's dev-capture badge (#8): a steady red dot whenever raw-audio
recording is armed, so it can never run silently. The glyph painter is module-
level, so the dot is testable offscreen without a real system tray."""

import pytest


def _qt(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])


def test_dev_dot_lights_the_corner(monkeypatch):
    _qt(monkeypatch)
    from PySide6.QtGui import QColor

    from tuparles.tray import _glyph

    grey = QColor(200, 200, 200)
    plain = _glyph(grey).pixmap(22, 22).toImage()
    dotted = _glyph(grey, dev_dot=True).pixmap(22, 22).toImage()
    # Centre of the dot rect (15,1,6,6): lit when armed, transparent when not
    # (the bars don't reach that top-right corner).
    assert dotted.pixelColor(18, 4).alpha() > 0
    assert plain.pixelColor(18, 4).alpha() == 0


def test_dev_dot_is_the_warning_hue(monkeypatch):
    _qt(monkeypatch)
    from PySide6.QtGui import QColor

    from tuparles.tray import _DEV_DOT, _glyph

    dotted = _glyph(QColor(200, 200, 200), dev_dot=True).pixmap(22, 22).toImage()
    px = dotted.pixelColor(18, 4)
    # the corner pixel is the dev-dot colour, not the bar grey
    assert (px.red(), px.green(), px.blue()) == (
        _DEV_DOT.red(),
        _DEV_DOT.green(),
        _DEV_DOT.blue(),
    )
