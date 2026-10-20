"""Is this machine running on its battery right now?

Read straight from `/sys/class/power_supply` — stdlib only, no UPower/D-Bus
dependency, nothing to install. The engine asks once per take (`battery_aware`
setting), so the answer is cached for a few seconds: a burst of takes costs one
directory walk, and a plug or unplug is still noticed by the next take.

The witness is the machine's own battery: any system battery reporting
`Discharging` means "on battery", **whatever the supplies say**. A supply's
`online` is not evidence of charging — a low-wattage USB-C PD charger, a dock,
or a UCSI port with a non-charging partner all report `online=1` while the
battery drains (the dev laptop, at ~45 % and falling, showed AC and one UCSI
port online). So supplies are never consulted: they can't prove we're on
battery, and they must not overrule a battery that says it is draining.

Everything else answers False: a desktop with no battery, a charging, full or
"not charging" (plugged, charge-limited) battery, an unreadable tree, a status we
don't recognise, a non-Linux box with no sysfs at all. False means "use the GPU
as before", so a probe that can't see keeps exactly the pre-feature behaviour
rather than silently slowing a desktop down to CPU.

Peripheral batteries (a wireless mouse or headset: `scope` = `Device`) are not
the machine's and are ignored.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

POWER_SUPPLY_ROOT = Path("/sys/class/power_supply")
CACHE_TTL_S = 5.0


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def read_on_battery(root: Path = POWER_SUPPLY_ROOT) -> bool:
    """Uncached probe. True iff a system battery reports Discharging."""
    try:
        supplies = sorted(root.iterdir())
    except OSError:
        return False
    for supply in supplies:
        kind = _read(supply / "type")
        if kind is None and supply.name.startswith("BAT"):
            kind = "Battery"  # older/odd drivers omit `type`; the name is enough
        if (
            kind == "Battery"
            and _read(supply / "scope") != "Device"  # not a mouse's cell
            and _read(supply / "status") == "Discharging"
        ):
            return True  # one draining pack is enough (dual-battery laptops)
    return False


class PowerProbe:
    """`read_on_battery` behind a short TTL cache. Root and clock injectable."""

    def __init__(
        self,
        root: Path = POWER_SUPPLY_ROOT,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root = root
        self._ttl_s = ttl_s
        self._clock = clock
        self._value = False
        self._read_at: float | None = None

    def on_battery(self) -> bool:
        now = self._clock()
        if self._read_at is None or now - self._read_at >= self._ttl_s:
            self._value = read_on_battery(self._root)
            self._read_at = now
        return self._value


_probe = PowerProbe()


def on_battery() -> bool:
    """The process-wide cached answer. Tests monkeypatch this name."""
    return _probe.on_battery()
