"""Global hotkey: Right Ctrl + Right Alt pressed together.

Tap = toggle (recording continues until the next tap). Hold = push-to-talk
(releasing the combo stops the take) — the listener only reports *what the
keys did* (combo engaged / combo released after N seconds); deciding what
that means for the recorder is the Controller's job.

X11 reports Right Alt as alt_r or alt_gr depending on layout, so both are
accepted.
"""

import time
from collections.abc import Callable

from pynput import keyboard

from tuparles.config import HOTKEY_DEBOUNCE_S

_RIGHT_CTRL = {keyboard.Key.ctrl_r}
_RIGHT_ALT = {keyboard.Key.alt_r, keyboard.Key.alt_gr}


class HotkeyListener:
    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_combo_release: Callable[[float], None] | None = None,
    ) -> None:
        self._on_toggle = on_toggle
        self._on_combo_release = on_combo_release
        self._pressed: set = set()
        self._last_fire = 0.0
        self._combo_since: float | None = None  # set while both keys are down
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )

    def start(self) -> None:
        self._listener.start()

    def join(self) -> None:
        self._listener.join()

    def stop(self) -> None:
        self._listener.stop()

    def _on_press(self, key) -> None:
        self._pressed.add(key)
        has_ctrl = bool(self._pressed & _RIGHT_CTRL)
        has_alt = bool(self._pressed & _RIGHT_ALT)
        if has_ctrl and has_alt and self._combo_since is None:
            now = time.monotonic()
            self._combo_since = now
            if now - self._last_fire >= HOTKEY_DEBOUNCE_S:
                self._last_fire = now
                self._on_toggle()

    def _on_release(self, key) -> None:
        self._pressed.discard(key)
        has_ctrl = bool(self._pressed & _RIGHT_CTRL)
        has_alt = bool(self._pressed & _RIGHT_ALT)
        if self._combo_since is not None and not (has_ctrl and has_alt):
            held = time.monotonic() - self._combo_since
            self._combo_since = None
            if self._on_combo_release is not None:
                self._on_combo_release(held)
