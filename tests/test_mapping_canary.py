"""The MappingNotify canary counts keymap-change broadcasts (#10). Counting is
tested with a faked event stream — no real X display — and the module is
fail-open by design (Wayland / no Xlib / dead display never affects delivery)."""

from tuparles import mapping_canary


class _Event:
    def __init__(self, type_):
        self.type = type_


def test_counts_only_mapping_notify_events(monkeypatch):
    mapping_canary._reset_for_test()
    other = mapping_canary._MAPPING_NOTIFY + 1  # any non-mapping event type
    for ev in (
        _Event(other),
        _Event(mapping_canary._MAPPING_NOTIFY),
        _Event(other),
        _Event(mapping_canary._MAPPING_NOTIFY),
        _Event(mapping_canary._MAPPING_NOTIFY),
    ):
        mapping_canary._note(ev)
    assert mapping_canary.count() == 3


def test_pump_drains_a_stream_and_fails_open_at_the_end():
    mapping_canary._reset_for_test()

    events = [
        _Event(mapping_canary._MAPPING_NOTIFY),
        _Event(0),
        _Event(mapping_canary._MAPPING_NOTIFY),
    ]

    class FakeConn:
        def next_event(self):
            if not events:
                raise OSError("display gone")  # ends the stream, fail-open
            return events.pop(0)

    mapping_canary._pump(FakeConn())
    assert mapping_canary.count() == 2
    # A dropped connection disables the canary rather than crash the thread.
    assert mapping_canary._disabled is True
    assert mapping_canary.enabled() is False


def test_start_is_idempotent_and_fail_open_on_wayland(monkeypatch):
    mapping_canary._reset_for_test()
    monkeypatch.setattr("tuparles.config.IS_WAYLAND", True, raising=False)
    threads = []
    monkeypatch.setattr(
        mapping_canary.threading, "Thread", lambda *a, **k: threads.append((a, k))
    )
    mapping_canary.start()
    mapping_canary.start()  # second call is a no-op
    assert threads == []  # Wayland → no listener thread, disabled
    assert mapping_canary.enabled() is False
    assert mapping_canary.count() == 0


def test_enabled_only_after_a_clean_arm(monkeypatch):
    mapping_canary._reset_for_test()
    assert mapping_canary.enabled() is False  # never started
    monkeypatch.setattr("tuparles.config.IS_WAYLAND", False, raising=False)
    started = []
    monkeypatch.setattr(
        mapping_canary.threading,
        "Thread",
        lambda *a, **k: type("T", (), {"start": lambda self: started.append(True)})(),
    )
    monkeypatch.setattr("Xlib.display.Display", lambda *a, **k: object(), raising=False)
    mapping_canary.start()
    assert mapping_canary.enabled() is True
    assert started == [True]
