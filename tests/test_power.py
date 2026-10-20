"""The power-source probe: is this box running on its battery right now?

Built against a fake `/sys/class/power_supply` tree, never the real one — the
suite must not change colour depending on whether the dev laptop is plugged in.

The rule under test: the machine's own battery is the witness. A system
battery (not a mouse's: scope=Device) reporting Discharging means "on battery",
whatever any supply's `online` says — a weak USB-C PD charger, a dock or a UCSI
port with a non-charging partner all report online while the battery drains.
Anything else — a desktop with no battery, a charging, full or not-charging
battery, a tree we can't read, a status we don't recognise — answers "not on
battery", so the engine keeps the GPU it would have used before this feature.
"""

from pathlib import Path

from tuparles.power import PowerProbe, read_on_battery


def _supply(root: Path, name: str, **attrs: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    for key, value in attrs.items():
        (d / key).write_text(value + "\n", encoding="utf-8")


def test_a_discharging_battery_means_on_battery(tmp_path):
    _supply(tmp_path, "AC", type="Mains", online="0")
    _supply(tmp_path, "BAT0", type="Battery", status="Discharging")
    assert read_on_battery(tmp_path) is True


def test_charging_full_or_not_charging_is_not_on_battery(tmp_path):
    for i, status in enumerate(("Charging", "Full", "Not charging")):
        root = tmp_path / str(i)
        _supply(root, "BAT0", type="Battery", status=status)
        assert read_on_battery(root) is False, status


def test_a_discharging_battery_wins_over_online_supplies(tmp_path):
    # The dev laptop's real tree, draining at ~45 %: AC and one UCSI port both
    # say online=1 (a dock / weak PD partner), yet the battery is discharging.
    # "Online" is not "charging"; the battery's own status is the witness.
    _supply(tmp_path, "AC", type="Mains", online="1")
    _supply(tmp_path, "BAT0", type="Battery", status="Discharging")
    _supply(tmp_path, "ucsi-source-psy-USBC000:001", type="USB", online="0")
    _supply(
        tmp_path,
        "ucsi-source-psy-USBC000:002",
        type="USB",
        online="1",
        scope="System",
    )
    _supply(tmp_path, "ucsi-source-psy-USBC000:003", type="USB", online="0")
    _supply(tmp_path, "ucsi-source-psy-USBC000:004", type="USB", online="0")
    assert read_on_battery(tmp_path) is True


def test_a_charged_battery_with_online_mains_is_not_on_battery(tmp_path):
    for i, status in enumerate(("Charging", "Full", "Not charging")):
        root = tmp_path / str(i)
        _supply(root, "AC", type="Mains", online="1")
        _supply(root, "BAT0", type="Battery", status=status)
        assert read_on_battery(root) is False, status


def test_one_discharging_system_battery_wins(tmp_path):
    # Dual-battery laptops (ThinkPad BAT0+BAT1) drain one pack at a time.
    _supply(tmp_path, "BAT0", type="Battery", status="Not charging")
    _supply(tmp_path, "BAT1", type="Battery", status="Discharging")
    assert read_on_battery(tmp_path) is True


def test_a_desktop_with_no_battery_is_not_on_battery(tmp_path):
    _supply(tmp_path, "AC", type="Mains", online="1")
    assert read_on_battery(tmp_path) is False


def test_an_empty_or_missing_tree_is_not_on_battery(tmp_path):
    assert read_on_battery(tmp_path) is False  # exists, empty (containers)
    assert read_on_battery(tmp_path / "nope") is False  # no sysfs at all (macOS)


def test_a_peripheral_battery_is_not_the_machines(tmp_path):
    # A wireless mouse draining its own cell must not push a desktop onto CPU —
    # alone, or next to mains that is online.
    _supply(tmp_path / "mains", "AC", type="Mains", online="1")
    _supply(
        tmp_path / "mains",
        "hidpp_battery_1",
        type="Battery",
        scope="Device",
        status="Discharging",
    )
    assert read_on_battery(tmp_path / "mains") is False
    _supply(
        tmp_path,
        "hidpp_battery_0",
        type="Battery",
        scope="Device",
        status="Discharging",
    )
    assert read_on_battery(tmp_path) is False


def test_unreadable_or_odd_status_is_not_on_battery(tmp_path):
    _supply(tmp_path, "BAT0", type="Battery", status="Unknown")
    assert read_on_battery(tmp_path) is False
    odd = tmp_path / "odd"
    _supply(odd, "BAT1", type="Battery")  # no status file at all
    assert read_on_battery(odd) is False


def test_a_bat_directory_without_a_type_file_still_counts(tmp_path):
    _supply(tmp_path, "BAT0", status="Discharging")
    assert read_on_battery(tmp_path) is True


def test_the_probe_caches_so_per_take_polling_is_free(tmp_path):
    _supply(tmp_path, "BAT0", type="Battery", status="Discharging")
    now = [100.0]
    probe = PowerProbe(root=tmp_path, ttl_s=5.0, clock=lambda: now[0])
    assert probe.on_battery() is True

    (tmp_path / "BAT0" / "status").write_text("Charging\n", encoding="utf-8")
    now[0] += 4.9
    assert probe.on_battery() is True  # still cached
    now[0] += 0.2
    assert probe.on_battery() is False  # cache expired, re-read sysfs
