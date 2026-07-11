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


def _rgb(c):
    return (c.red(), c.green(), c.blue())


def test_state_color_recording_is_full_engine_hue(monkeypatch):
    _qt(monkeypatch)
    from tuparles.tray import _CPU, _GPU, state_color

    # hue is the engine identity: green=GPU, blue=CPU, at full strength while live
    assert _rgb(state_color("recording", "gpu")) == _rgb(_GPU)
    assert _rgb(state_color("recording", "cpu")) == _rgb(_CPU)


def test_state_color_cpu_idle_is_a_persistent_signal(monkeypatch):
    _qt(monkeypatch)
    from tuparles.tray import _CPU_IDLE, _IDLE, state_color

    # GPU at rest = neutral; CPU at rest = a persistent muted-blue signal (#131),
    # so a glance at the idle tray still tells you you're on the fallback rung.
    assert _rgb(state_color("idle", "gpu")) == _rgb(_IDLE)
    assert _rgb(state_color("idle", "cpu")) == _rgb(_CPU_IDLE)
    assert _rgb(state_color("idle", "cpu")) != _rgb(_IDLE)


def test_state_color_cpu_idle_is_dimmer_than_active(monkeypatch):
    _qt(monkeypatch)
    from tuparles.tray import state_color

    # the second-state signal is brightness/saturation, not a hue flip: the idle
    # CPU tint is visibly darker than the active CPU tint.
    active = state_color("recording", "cpu")
    idle = state_color("idle", "cpu")
    assert sum(_rgb(idle)) < sum(_rgb(active))
