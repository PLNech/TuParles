"""The combo edge detector: one fire per physical press, a short chatter guard
on re-press, and hold-release reporting. No real keyboard — we drive the state
machine directly and control the clock, since the bug we care about (rapid
toggles silently eaten) is purely about timing."""

import pytest

from tuparles import hotkey
from tuparles.hotkey import _ComboState


def _state(monkeypatch, clock):
    """A _ComboState whose time.monotonic() is `clock[0]` (mutate to advance)."""
    monkeypatch.setattr(hotkey.time, "monotonic", lambda: clock[0])
    fires = []
    releases = []
    st = _ComboState(lambda: fires.append(clock[0]), releases.append)
    return st, fires, releases


def test_single_press_fires_once(monkeypatch):
    clock = [10.0]
    st, fires, _ = _state(monkeypatch, clock)
    st.update(True, True)  # both down
    st.update(True, True)  # still down — must NOT re-fire (edge detector)
    assert fires == [10.0]


def test_release_reports_hold_duration(monkeypatch):
    clock = [100.0]
    st, fires, releases = _state(monkeypatch, clock)
    st.update(True, True)  # press
    clock[0] = 100.8
    st.update(True, False)  # alt up → combo released after 0.8 s
    assert releases == [pytest.approx(0.8)]


def test_rapid_repress_after_debounce_fires(monkeypatch):
    """A start then a stop 0.2 s later (> 0.12 s guard) must both register —
    this is the rapid-toggle case that 0.4 s used to eat."""
    clock = [100.0]
    st, fires, _ = _state(monkeypatch, clock)
    st.update(True, True)  # start
    st.update(True, False)  # release
    clock[0] = 100.2
    st.update(True, True)  # stop, 0.2 s later
    assert fires == [100.0, pytest.approx(100.2)]


def test_chatter_within_guard_is_dropped(monkeypatch):
    """A re-engage within the chatter guard (switch bounce) fires once only."""
    clock = [100.0]
    st, fires, _ = _state(monkeypatch, clock)
    st.update(True, True)  # fire
    st.update(True, False)  # release
    clock[0] = 100.05  # 50 ms — chatter, under the 0.12 s guard
    st.update(True, True)
    assert fires == [100.0]  # the bounce did not double-fire


def test_force_release_ends_a_held_chord(monkeypatch):
    """A focus change that swallows the key-up must still report the hold.

    That is the Mac click / Cmd-Tab case: the release never arrives, so the
    listener clears the pressed set itself.
    """
    clock = [50.0]
    st, fires, releases = _state(monkeypatch, clock)
    listener = hotkey._PynputListener.__new__(hotkey._PynputListener)
    listener._state = st
    listener._pressed = {"cmd_r", "alt_r"}
    listener._right_ctrl = {"cmd_r"}
    listener._right_alt = {"alt_r"}
    listener._focus_watch = None
    listener._update()  # both keys down, the chord engages
    clock[0] = 51.2
    listener.force_release()
    assert releases == [pytest.approx(1.2)]
    assert fires == [50.0]
    # A second focus blip with nothing held is a no-op.
    listener.force_release()
    assert releases == [pytest.approx(1.2)]


def test_macos_chord_is_right_option_and_right_command(monkeypatch):
    """The built-in keyboard has no right Control. The two right-hand
    modifiers are Right Option and Right Command."""
    import sys
    import types

    keys = types.SimpleNamespace(
        cmd_r="cmd_r", alt_r="alt_r", alt_gr="alt_gr", ctrl_r="ctrl_r", esc="esc"
    )
    keyboard = types.SimpleNamespace(Key=keys, Listener=lambda **k: None)
    monkeypatch.setitem(sys.modules, "pynput", types.SimpleNamespace(keyboard=keyboard))
    monkeypatch.setitem(
        sys.modules, "pynput.keyboard", types.SimpleNamespace(Key=keys, Listener=lambda **k: None)
    )
    monkeypatch.setattr(hotkey, "IS_MACOS", True)
    listener = hotkey._PynputListener(lambda: None)
    assert listener._right_ctrl == {"cmd_r"}
    assert listener._right_alt == {"alt_r"}


def test_linux_chord_stays_right_ctrl_and_right_alt(monkeypatch):
    import sys
    import types

    keys = types.SimpleNamespace(
        cmd_r="cmd_r", alt_r="alt_r", alt_gr="alt_gr", ctrl_r="ctrl_r", esc="esc"
    )
    monkeypatch.setitem(
        sys.modules, "pynput.keyboard", types.SimpleNamespace(Key=keys, Listener=lambda **k: None)
    )
    monkeypatch.setitem(
        sys.modules, "pynput", types.SimpleNamespace(keyboard=sys.modules["pynput.keyboard"])
    )
    monkeypatch.setattr(hotkey, "IS_MACOS", False)
    listener = hotkey._PynputListener(lambda: None)
    assert listener._right_ctrl == {"ctrl_r"}
    assert listener._right_alt == {"alt_r", "alt_gr"}


def test_held_combo_does_not_retrigger(monkeypatch):
    """Holding the combo (push-to-talk) is one fire; partial key wiggle while
    still holding both must not re-fire."""
    clock = [100.0]
    st, fires, _ = _state(monkeypatch, clock)
    st.update(True, True)  # engage
    clock[0] = 101.0
    st.update(True, True)  # still holding a second later
    assert fires == [100.0]
