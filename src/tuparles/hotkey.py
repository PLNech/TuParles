"""Global hotkey: Right Ctrl + Right Alt pressed together.

Tap = toggle (recording continues until the next tap). Hold = push-to-talk
(releasing the combo stops the take) — the listener only reports *what the
keys did* (combo engaged / combo released after N seconds); deciding what
that means for the recorder is the Controller's job.

Two backends, one contract:
- X11: pynput (XRecord) hears every key. X11 reports Right Alt as alt_r
  or alt_gr depending on layout, so both are accepted.
- Wayland: the compositor never forwards global keys to clients (that's
  the security model, not a bug), so pynput is deaf there. The evdev
  backend reads /dev/input *below* the compositor instead — needs the
  user in the `input` group; scripts/setup_wayland.sh sets that up.
"""

import selectors
import threading
import time
from collections.abc import Callable

from tuparles.config import HOTKEY_DEBOUNCE_S, IS_WAYLAND

# evdev keycodes are layout-blind: AltGr on an azerty keyboard is still
# KEY_RIGHTALT at this level, so no alt_r/alt_gr split like X11 has.
_EV_KEY = 0x01
_KEY_ESC = 1
_KEY_RIGHTCTRL = 97
_KEY_RIGHTALT = 100


class _ComboState:
    """Edge detector shared by both backends: fires on_toggle when both
    keys go down, reports the hold duration when the combo lets go."""

    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_combo_release: Callable[[float], None] | None,
    ) -> None:
        self._on_toggle = on_toggle
        self._on_combo_release = on_combo_release
        self._last_fire = 0.0
        self._combo_since: float | None = None  # set while both keys are down

    def update(self, has_ctrl: bool, has_alt: bool) -> None:
        if has_ctrl and has_alt:
            if self._combo_since is None:
                now = time.monotonic()
                self._combo_since = now
                if now - self._last_fire >= HOTKEY_DEBOUNCE_S:
                    self._last_fire = now
                    self._on_toggle()
        elif self._combo_since is not None:
            held = time.monotonic() - self._combo_since
            self._combo_since = None
            if self._on_combo_release is not None:
                self._on_combo_release(held)


class _PynputListener:
    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_combo_release: Callable[[float], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        from pynput import keyboard

        self._right_ctrl = {keyboard.Key.ctrl_r}
        self._right_alt = {keyboard.Key.alt_r, keyboard.Key.alt_gr}
        self._esc = keyboard.Key.esc  # _on_press runs after __init__ returns,
        # where the local `keyboard` is gone — capture the key object now.
        self._state = _ComboState(on_toggle, on_combo_release)
        self._on_cancel = on_cancel
        self._pressed: set = set()
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )

    def start(self) -> None:
        self._listener.start()

    def join(self) -> None:
        self._listener.join()

    def stop(self) -> None:
        self._listener.stop()

    def _update(self) -> None:
        self._state.update(
            bool(self._pressed & self._right_ctrl),
            bool(self._pressed & self._right_alt),
        )

    def _on_press(self, key) -> None:
        # Esc aborts an in-flight take. We only *observe* it (pynput doesn't
        # suppress), so Esc still reaches the focused app — the controller
        # no-ops unless we're recording, making this a free global cancel.
        if key == self._esc and self._on_cancel is not None:
            self._on_cancel()
        self._pressed.add(key)
        self._update()

    def _on_release(self, key) -> None:
        self._pressed.discard(key)
        self._update()


class _EvdevListener:
    """Reads keyboards straight from /dev/input — works under any
    compositor, X11 included. Devices are rescanned every few seconds so
    a keyboard plugged in mid-session still triggers takes."""

    _RESCAN_S = 5.0

    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_combo_release: Callable[[float], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        self._state = _ComboState(on_toggle, on_combo_release)
        self._on_cancel = on_cancel
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="hotkey-evdev", daemon=True
        )

    @staticmethod
    def keyboard_paths(skip=()) -> list[str]:
        """Readable devices that physically have a Right Ctrl key, minus any
        path in `skip` (already-watched ones — no point reopening them every
        rescan). Skips ydotool's virtual keyboard: watching our own delivery
        tool would let a pasted take re-trigger the listener."""
        import evdev

        paths = []
        for path in evdev.list_devices():
            if path in skip:
                continue
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            try:
                if "ydotool" in (dev.name or "").lower():
                    continue
                if _KEY_RIGHTCTRL in dev.capabilities().get(_EV_KEY, []):
                    paths.append(path)
            finally:
                dev.close()
        return paths

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join()

    def stop(self) -> None:
        # Signal only — don't join. The daemon thread notices within its
        # select() timeout and closes the devices itself; blocking the GUI
        # thread on the join would stall quit/restart by up to a second, and
        # process teardown closes the fds regardless (they're read, not
        # exclusively grabbed, so nothing else is waiting on them).
        self._stop_evt.set()

    def _loop(self) -> None:
        import evdev

        sel = selectors.DefaultSelector()
        watched: dict[str, evdev.InputDevice] = {}
        # Modifier state per device: Ctrl on one keyboard must not combine
        # with Alt on another (or a stuck modifier on an idle second board)
        # into a phantom combo. Both keys must be down on the same device.
        down: dict[str, dict[int, bool]] = {}
        warned: set[str] = set()
        last_scan = -self._RESCAN_S
        while not self._stop_evt.is_set():
            now = time.monotonic()
            if now - last_scan >= self._RESCAN_S:
                last_scan = now
                for path in self.keyboard_paths(skip=watched):
                    try:
                        dev = evdev.InputDevice(path)
                        sel.register(dev, selectors.EVENT_READ)
                        watched[path] = dev
                        down[path] = {_KEY_RIGHTCTRL: False, _KEY_RIGHTALT: False}
                    except OSError as e:
                        if path not in warned:
                            warned.add(path)
                            print(f"hotkey: {path} illisible ({e}) — ignoré")
            for key, _ in sel.select(timeout=1.0):
                dev = key.fileobj
                try:
                    events = list(dev.read())
                except OSError:  # unplugged mid-read
                    sel.unregister(dev)
                    watched.pop(dev.path, None)
                    down.pop(dev.path, None)
                    dev.close()
                    continue
                dev_down = down[dev.path]
                for ev in events:
                    if ev.type != _EV_KEY:
                        continue
                    # Esc press aborts an in-flight take. Unlike pynput we
                    # don't suppress, so Esc still reaches the focused app;
                    # the controller no-ops unless recording (free cancel).
                    if (
                        ev.code == _KEY_ESC
                        and ev.value == 1
                        and self._on_cancel is not None
                    ):
                        self._on_cancel()
                        continue
                    # value: 1 press, 0 release, 2 autorepeat (ignored —
                    # a held combo must not re-toggle the recorder).
                    if ev.code in dev_down and ev.value in (0, 1):
                        dev_down[ev.code] = bool(ev.value)
                        self._state.update(
                            dev_down[_KEY_RIGHTCTRL],
                            dev_down[_KEY_RIGHTALT],
                        )
        for dev in watched.values():
            dev.close()


def HotkeyListener(
    on_toggle: Callable[[], None],
    on_combo_release: Callable[[float], None] | None = None,
    on_cancel: Callable[[], None] | None = None,
):
    """Pick the backend that can actually hear the keys in this session."""
    if IS_WAYLAND:
        try:
            if _EvdevListener.keyboard_paths():
                print("Hotkey: evdev (Wayland)")
                return _EvdevListener(on_toggle, on_combo_release, on_cancel)
        except Exception as e:
            print(f"Hotkey: evdev indisponible ({e})")
        print(
            "Wayland sans accès /dev/input : le raccourci global ne marchera "
            "que dans les fenêtres X11. Lance scripts/setup_wayland.sh puis "
            "rouvre ta session."
        )
    return _PynputListener(on_toggle, on_combo_release, on_cancel)
