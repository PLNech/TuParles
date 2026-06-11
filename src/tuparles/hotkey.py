"""Global hotkey: Right Ctrl + Right Alt pressed together → toggle event.

X11 reports Right Alt as alt_r or alt_gr depending on layout, so both are
accepted. Hold-to-talk mode comes later; the demo spine is tap-toggle.
"""

import time
from collections.abc import Callable

from pynput import keyboard

from tuparles.config import HOTKEY_DEBOUNCE_S

_RIGHT_CTRL = {keyboard.Key.ctrl_r}
_RIGHT_ALT = {keyboard.Key.alt_r, keyboard.Key.alt_gr}


class HotkeyListener:
    def __init__(self, on_toggle: Callable[[], None]) -> None:
        self._on_toggle = on_toggle
        self._pressed: set = set()
        self._last_fire = 0.0
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
        if has_ctrl and has_alt:
            now = time.monotonic()
            if now - self._last_fire >= HOTKEY_DEBOUNCE_S:
                self._last_fire = now
                self._on_toggle()

    def _on_release(self, key) -> None:
        self._pressed.discard(key)
