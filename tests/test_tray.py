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


# ---------------------------------------------------------------------------
# Icon churn (the 24/7 D-Bus cost). On SNI trays (GNOME appindicator, KDE) every
# QSystemTrayIcon.setIcon becomes an org.kde.StatusNotifierItem.NewIcon signal —
# Qt emits it unconditionally, it never compares frames — and the shell then
# fetches and decodes a fresh pixmap on its main thread. A steady 10 Hz breath at
# rest grew gnome-shell's heap ~450 MiB/12 h and stalled its main loop. These
# tests pin the contract: zero updates at rest, a low capped rate only while a
# take is live, and never the same frame twice in a row.
# ---------------------------------------------------------------------------


class _Spy:
    """Records what reaches the (fake) system tray icon."""

    def __init__(self):
        self.icons = []  # every QIcon passed to setIcon, in order

    @property
    def count(self):
        return len(self.icons)

    def reset(self):
        self.icons.clear()


@pytest.fixture
def make_tray(monkeypatch):
    """Build a Tray on a fake QSystemTrayIcon whose setIcon is counted. Returns a
    factory: make_tray(animate=True, backend=...) -> (tray, spy). `backend` is a
    one-item list so a test can flip the engine colour under the tray's feet."""
    _qt(monkeypatch)
    from PySide6.QtCore import QObject

    import tuparles.tray as tray_mod
    from tuparles import settings

    spy = _Spy()

    class _FakeTrayIcon(QObject):
        def __init__(self, icon=None, parent=None):
            super().__init__(parent)
            self.ctor_icon = icon

        def setIcon(self, icon):
            spy.icons.append(icon)

        def setContextMenu(self, _menu):
            pass

        def setToolTip(self, _tip):
            pass

        def show(self):
            pass

    monkeypatch.setattr(tray_mod, "QSystemTrayIcon", _FakeTrayIcon)

    def factory(animate=True, backend=None):
        settings.put("tray_animation", animate)
        backend = backend if backend is not None else ["gpu"]
        tray = tray_mod.Tray(backend_source=lambda: backend[0])
        spy.reset()  # the constructor's own icon is not churn
        return tray, spy

    return factory


def _advance(tray, seconds: float) -> int:
    """Simulated time: fire the tray's animation timer as often as it would fire
    in `seconds` of wall clock, but only while it is actually running. Returns
    the number of ticks delivered."""
    interval = tray._timer.interval()
    assert interval > 0
    ticks = 0
    for _ in range(int(seconds * 1000 // interval)):
        if not tray._timer.isActive():
            break
        tray._tick()
        ticks += 1
    return ticks


def _set_anim(on: bool):
    from tuparles import settings

    settings.put("tray_animation", on)


def test_idle_emits_zero_updates_over_an_hour(make_tray):
    tray, spy = make_tray(animate=True)
    assert not tray._timer.isActive(), "the timer must not run at rest"
    _advance(tray, 3600)
    assert spy.count == 0


def test_idle_emits_zero_updates_in_real_time(make_tray):
    """The real event loop agrees with the simulated clock: at rest nothing
    fires, however long the loop spins."""
    import time

    from PySide6.QtWidgets import QApplication

    tray, spy = make_tray(animate=True)
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert spy.count == 0


@pytest.mark.parametrize("state", ["recording", "processing"])
def test_active_rate_is_capped_at_two_hz(make_tray, state):
    tray, spy = make_tray(animate=True)
    tray.set_state(state)
    assert tray._timer.isActive(), f"{state} animates when the setting is on"
    assert 1000 / tray._timer.interval() <= 2.0
    spy.reset()
    _advance(tray, 10)
    assert spy.count <= 2 * 10
    assert spy.count >= 10, "the animation must still be alive while active"


@pytest.mark.parametrize("state", ["recording", "processing"])
def test_active_animation_has_distinct_frames(make_tray, state):
    """Throttled, not killed: a live take still visibly moves."""
    tray, spy = make_tray(animate=True)
    tray.set_state(state)
    _advance(tray, 10)
    assert len({icon.cacheKey() for icon in spy.icons}) >= 3


def test_identical_consecutive_frames_never_reach_set_icon(make_tray):
    """'Identical' means pixel-identical — what the shell would decode — not
    'same QIcon object': a fresh QIcon of the same picture is still churn."""
    tray, spy = make_tray(animate=True)
    tray.set_state("idle")  # already idle
    for state in ["recording", "recording", "processing", "processing", "idle"]:
        tray.set_state(state)
        _advance(tray, 6)
    tray.set_state("idle")
    tray.set_state("idle")
    images = [icon.pixmap(22, 22).toImage() for icon in spy.icons]
    assert images, "something must have been drawn"
    repeats = [i for i in range(1, len(images)) if images[i] == images[i - 1]]
    assert repeats == [], f"setIcon re-sent an unchanged frame at {repeats}"


def test_rest_glyph_is_the_static_pose(make_tray):
    """Rest shows the static rest pose: what you see at idle is the glyph the
    animation-off path shows, so turning animation on changes nothing at rest."""
    tray_on, spy_on = make_tray(animate=True)
    img_on = tray_on._current_icon.pixmap(22, 22).toImage()
    tray_off, _ = make_tray(animate=False)
    img_off = tray_off._current_icon.pixmap(22, 22).toImage()
    assert img_on == img_off


def test_same_frame_reuses_the_same_icon(make_tray):
    """Frames are cached by key: a frame seen before comes back as the very same
    QIcon (same cacheKey), which is what lets the dedupe compare cheaply."""
    tray, spy = make_tray(animate=False)
    tray.set_state("recording")
    tray.set_state("idle")
    tray.set_state("recording")
    assert spy.icons[0].cacheKey() == spy.icons[2].cacheKey()


def test_repeated_same_state_is_a_no_op(make_tray):
    tray, spy = make_tray(animate=False)
    tray.set_state("recording")
    assert spy.count == 1
    tray.set_state("recording")
    tray.set_state("recording")
    assert spy.count == 1


def test_lifecycle_starts_and_stops_the_timer(make_tray):
    tray, spy = make_tray(animate=True)
    assert not tray._timer.isActive()
    tray.set_state("recording")
    assert tray._timer.isActive()
    tray.set_state("processing")
    assert tray._timer.isActive()
    before = spy.count
    tray.on_final("bonjour le monde")  # the final lands: menu work, no repaint
    assert spy.count == before
    tray.set_state("idle")
    assert not tray._timer.isActive()
    spy.reset()
    _advance(tray, 600)
    assert spy.count == 0


def test_rapid_flapping_leaves_one_stopped_timer(make_tray):
    import random

    from PySide6.QtCore import QTimer

    tray, spy = make_tray(animate=True)
    rng = random.Random(1234)
    for _ in range(500):
        tray.set_state(rng.choice(["idle", "recording", "processing", "error"]))
        if rng.random() < 0.3 and tray._timer.isActive():
            tray._tick()
    tray.set_state("idle")
    timers = tray.findChildren(QTimer)
    assert len(timers) == 1
    assert timers[0] is tray._timer
    assert not tray._timer.isActive()
    spy.reset()
    _advance(tray, 600)
    assert spy.count == 0


def test_live_toggle_on_off_on(make_tray):
    tray, spy = make_tray(animate=True)
    tray.set_state("recording")
    assert tray._timer.isActive()

    _set_anim(False)
    tray.apply_live_settings()
    assert not tray._timer.isActive()
    spy.reset()
    _advance(tray, 30)
    assert spy.count == 0

    _set_anim(True)
    tray.apply_live_settings()
    assert tray._timer.isActive(), "re-enabled mid-take: the take animates again"
    spy.reset()
    _advance(tray, 5)
    assert 5 <= spy.count <= 10

    _set_anim(False)
    tray.apply_live_settings()
    assert not tray._timer.isActive()


def test_live_toggle_on_at_rest_keeps_the_timer_off(make_tray):
    tray, spy = make_tray(animate=False)
    _set_anim(True)
    tray.apply_live_settings()
    assert not tray._timer.isActive(), "enabling animation never animates rest"
    assert spy.count == 0, "nothing visible changed at rest"


def test_apply_live_settings_without_change_is_silent(make_tray):
    tray, spy = make_tray(animate=True)
    tray.apply_live_settings()
    tray.apply_live_settings()
    assert spy.count == 0


def test_animation_off_one_update_per_state_change(make_tray):
    tray, spy = make_tray(animate=False)
    for state in ["recording", "processing", "idle"]:
        tray.set_state(state)
        assert not tray._timer.isActive()
    assert spy.count == 3
    _advance(tray, 600)
    assert spy.count == 3


def test_error_state_is_static(make_tray):
    tray, spy = make_tray(animate=True)
    tray.set_state("recording")
    spy.reset()
    tray.set_state("error")
    assert not tray._timer.isActive(), "an unknown/error state never animates"
    assert spy.count == 1
    _advance(tray, 600)
    assert spy.count == 1


def test_backend_flip_at_rest_is_exactly_one_update(make_tray):
    backend = ["gpu"]
    tray, spy = make_tray(animate=True, backend=backend)
    backend[0] = "cpu"  # the sticky CPU fallback engaged
    tray.refresh()
    assert spy.count == 1
    tray.refresh()
    tray.refresh()
    assert spy.count == 1
    assert not tray._timer.isActive()


def test_backend_flip_is_picked_up_on_the_idle_transition(make_tray):
    from tuparles.tray import _CPU_IDLE

    backend = ["gpu"]
    tray, spy = make_tray(animate=False, backend=backend)
    tray.set_state("processing")
    backend[0] = "cpu"  # fell back during the decode
    tray.set_state("idle")
    assert spy.count == 2
    px = spy.icons[-1].pixmap(22, 22).toImage().pixelColor(11, 11)  # middle bar
    assert _rgb(px) == _rgb(_CPU_IDLE)


def test_dev_capture_toggle_at_rest_is_one_update(make_tray):
    from tuparles import settings

    tray, spy = make_tray(animate=True)
    settings.put("dev_recording", True)
    tray.apply_live_settings()
    assert spy.count == 1
    tray.apply_live_settings()
    assert spy.count == 1


def test_frame_cache_is_bounded(make_tray):
    from tuparles import settings
    from tuparles.tray import _ICON_CACHE_MAX

    backend = ["gpu"]
    tray, spy = make_tray(animate=True, backend=backend)
    tray.set_state("recording")
    _advance(tray, 1000)
    after_long_take = len(tray._icon_cache)
    _advance(tray, 1000)
    assert len(tray._icon_cache) == after_long_take, "no growth with ticks"
    # every state x engine x dev-dot combination still fits the bound
    for dev in (False, True):
        settings.put("dev_recording", dev)
        tray.apply_live_settings()
        for b in ("gpu", "cpu"):
            backend[0] = b
            for state in ("idle", "recording", "processing", "error"):
                tray.set_state(state)
                _advance(tray, 20)
    assert len(tray._icon_cache) <= _ICON_CACHE_MAX


def test_ticks_do_not_paint_once_the_cycle_is_cached(make_tray, monkeypatch):
    import tuparles.tray as tray_mod

    tray, spy = make_tray(animate=True)
    tray.set_state("recording")
    _advance(tray, 10)  # warm one full cycle
    painted = []
    real = tray_mod._glyph
    monkeypatch.setattr(
        tray_mod, "_glyph", lambda *a, **k: painted.append(1) or real(*a, **k)
    )
    _advance(tray, 60)
    assert painted == [], "a cached frame must not be re-rendered per tick"


def test_ticks_do_not_read_settings(make_tray, monkeypatch):
    """settings.get reads settings.json from disk on every call; a tick must
    not, or the animation turns into a file read per frame."""
    from tuparles import settings

    tray, spy = make_tray(animate=True)
    tray.set_state("recording")
    reads = []
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: reads.append(k) or real(k))
    _advance(tray, 10)
    assert reads == []
