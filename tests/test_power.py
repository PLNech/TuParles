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
    # settle_s=0: this test is about the TTL alone; hysteresis is pinned below.
    probe = PowerProbe(root=tmp_path, ttl_s=5.0, settle_s=0.0, clock=lambda: now[0])
    assert probe.on_battery() is True

    (tmp_path / "BAT0" / "status").write_text("Charging\n", encoding="utf-8")
    now[0] += 4.9
    assert probe.on_battery() is True  # still cached
    now[0] += 0.2
    assert probe.on_battery() is False  # cache expired, re-read sysfs


class TestReplugHysteresis:
    """A marginal charger flips BAT0 Discharging<->Charging; each return to the
    GPU costs a ~1.6 s CUDA rebuild. So unplug is honoured at once (CPU is the
    safe side), but mains must hold steady for `settle_s` before we report it."""

    @staticmethod
    def _rig(tmp_path, status, settle_s=30.0):
        _supply(tmp_path, "BAT0", type="Battery", status=status)
        now = [1000.0]
        probe = PowerProbe(
            root=tmp_path, ttl_s=0.0, settle_s=settle_s, clock=lambda: now[0]
        )

        def set_status(value):
            (tmp_path / "BAT0" / "status").write_text(value + "\n", encoding="utf-8")

        return probe, now, set_status

    def test_cold_start_on_ac_trusts_the_first_reading(self, tmp_path):
        probe, _now, _set = self._rig(tmp_path, "Charging")
        assert probe.on_battery() is False  # no 30 s wait at launch

    def test_cold_start_on_battery_trusts_the_first_reading(self, tmp_path):
        probe, _now, _set = self._rig(tmp_path, "Discharging")
        assert probe.on_battery() is True

    def test_unplug_is_immediate(self, tmp_path):
        probe, now, set_status = self._rig(tmp_path, "Charging")
        assert probe.on_battery() is False
        set_status("Discharging")
        now[0] += 0.1
        assert probe.on_battery() is True

    def test_replug_waits_for_a_stable_window(self, tmp_path):
        probe, now, set_status = self._rig(tmp_path, "Discharging")
        assert probe.on_battery() is True
        set_status("Charging")
        assert probe.on_battery() is True  # t=0 of the calm window
        now[0] += 29.9
        assert probe.on_battery() is True  # not yet
        now[0] += 0.1
        assert probe.on_battery() is False  # 30 s of steady mains

    def test_a_discharging_blip_resets_the_window(self, tmp_path):
        probe, now, set_status = self._rig(tmp_path, "Discharging")
        assert probe.on_battery() is True
        set_status("Charging")
        assert probe.on_battery() is True  # calm since t=0
        now[0] += 20.0
        set_status("Discharging")  # the weak charger sags
        assert probe.on_battery() is True
        set_status("Charging")
        now[0] += 1.0
        assert probe.on_battery() is True  # calm restarts at t=21
        now[0] += 29.0
        assert probe.on_battery() is True  # t=50: only 29 s calm
        now[0] += 1.0
        assert probe.on_battery() is False  # t=51: 30 s calm

    def test_steady_ac_stays_false(self, tmp_path):
        probe, now, _set = self._rig(tmp_path, "Full")
        for _ in range(10):
            assert probe.on_battery() is False
            now[0] += 7.0

    def test_settle_window_is_a_module_constant_of_30_s(self):
        from tuparles import power

        assert power.REPLUG_SETTLE_S == 30.0


class TestLongGapIsAColdStart:
    """Hysteresis absorbs flapping between *close* reads. A gap longer than the
    settle window carries no flapping evidence, so the next read is trusted
    as-is: after a long idle on mains the very first take is back on the GPU."""

    _rig = staticmethod(TestReplugHysteresis._rig)

    def test_replug_after_a_long_idle_is_honoured_at_once(self, tmp_path):
        probe, now, set_status = self._rig(tmp_path, "Discharging")
        assert probe.on_battery() is True  # unplugged
        set_status("Charging")
        now[0] += 600.0  # 10 min idle, plugged back in meanwhile
        assert probe.on_battery() is False  # GPU on the first take

    def test_a_close_replug_read_still_waits(self, tmp_path):
        probe, now, set_status = self._rig(tmp_path, "Discharging")
        assert probe.on_battery() is True
        set_status("Charging")
        now[0] += 5.0
        assert probe.on_battery() is True  # inside the window, as before

    def test_a_discharging_read_after_a_long_gap_is_on_battery(self, tmp_path):
        probe, now, set_status = self._rig(tmp_path, "Charging")
        assert probe.on_battery() is False
        set_status("Discharging")
        now[0] += 600.0
        assert probe.on_battery() is True

    def test_flapping_with_short_gaps_still_holds_the_window(self, tmp_path):
        probe, now, set_status = self._rig(tmp_path, "Discharging")
        assert probe.on_battery() is True
        for _ in range(4):  # 25 s gaps, each under the 30 s window
            set_status("Charging")
            now[0] += 25.0
            assert probe.on_battery() is True
            set_status("Discharging")
            now[0] += 25.0
            assert probe.on_battery() is True

    def test_staleness_counts_from_the_last_sysfs_read_not_a_cache_hit(self, tmp_path):
        # With the real 5 s TTL: calls inside the TTL are cache hits and must
        # not refresh the "last read" time the staleness check uses.
        _supply(tmp_path, "BAT0", type="Battery", status="Discharging")
        now = [1000.0]
        probe = PowerProbe(
            root=tmp_path, ttl_s=5.0, settle_s=30.0, clock=lambda: now[0]
        )
        assert probe.on_battery() is True  # sysfs read at t=0
        (tmp_path / "BAT0" / "status").write_text("Charging\n", encoding="utf-8")
        for _ in range(4):
            now[0] += 1.0
            assert probe.on_battery() is True  # t=1..4: cache hits
        now[0] = 1031.0
        # Last sysfs read was t=0 (31 s ago): a cold start, so False. Had the
        # t=4 cache hit counted, the gap would be 27 s and the window would
        # only just be starting.
        assert probe.on_battery() is False
