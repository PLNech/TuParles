"""A read-only MappingNotify canary: count XKB keymap-change broadcasts on the
daemon's X display so a delivery burst can be correlated, per take, with the
gnome-shell keybinding-regrab storm that once froze the desktop (#10).

MappingNotify is broadcast to EVERY X client unconditionally (it carries no
event mask), so a client that merely pumps its own connection sees every keymap
change any client causes — including the scratch-keycode remaps `xdotool type`
triggers, and, as tonight's real-session forensics showed, the paste keystrokes
themselves under a live XKB config (2 pastes → 2 MappingNotify → 2 rebind
bursts). Counting them turns "did this delivery churn the keymap?" from a hunch
into a number the journal can quote.

Fail-open by construction. X11-only, best-effort, read-only (it opens a display
and READS events; it never sends input). Any failure — Wayland, no python-xlib,
no reachable display, a dropped connection — disables the canary with one line
and count() stays 0 forever after. It must never affect delivery."""

import threading

# X.MappingNotify is a stable X11 protocol constant (34). Import the symbol when
# python-xlib is present; fall back to the literal so this module imports even on
# a box without Xlib (count() just never moves there).
try:
    from Xlib import X as _X

    _MAPPING_NOTIFY = _X.MappingNotify
except Exception:  # pragma: no cover - exercised only where Xlib is absent
    _MAPPING_NOTIFY = 34

_count = 0
_lock = threading.Lock()
_started = False
_disabled = False


def count() -> int:
    """MappingNotify events seen since the canary armed (0 if it never did)."""
    return _count


def enabled() -> bool:
    """True while the canary is actually counting — so callers can skip a
    meaningless `+0` when it never armed or has since been disabled."""
    return _started and not _disabled


def _note(event) -> None:
    """Tally one event iff it's a MappingNotify. Split out so the counting logic
    is unit-testable with a faked event stream (no real X display needed)."""
    global _count
    if getattr(event, "type", None) == _MAPPING_NOTIFY:
        with _lock:
            _count += 1


def _pump(conn) -> None:
    """Read events forever, counting keymap changes. Fail-open: any error (the
    connection dropping, the display going away) ends the loop quietly and marks
    the canary disabled — the daemon keeps delivering, just without the gauge."""
    global _disabled
    try:
        while True:
            _note(conn.next_event())
    except Exception:
        _disabled = True


def start() -> None:
    """Arm the listener once, in a daemon thread. Idempotent and fail-open:
    Wayland, a missing python-xlib, or no reachable display disables it with one
    `deliver:`-tagged warning and count() stays 0 — never a delivery side effect."""
    global _started, _disabled
    if _started or _disabled:
        return
    _started = True
    try:
        from tuparles.config import IS_WAYLAND

        if IS_WAYLAND:
            # No X keymap to churn (and no MappingNotify) under Wayland proper.
            _disabled = True
            return
        from Xlib import display as _display

        conn = _display.Display()
    except Exception as exc:
        _disabled = True
        print(
            f"deliver: mapping-notify canary disabled "
            f"({str(exc)[:80]}); keymap churn will not be counted"
        )
        return
    threading.Thread(
        target=_pump, args=(conn,), daemon=True, name="mapping-canary"
    ).start()


def _reset_for_test() -> None:
    """Zero the module state between unit tests (the counter is process-global)."""
    global _count, _started, _disabled
    _count = 0
    _started = False
    _disabled = False
