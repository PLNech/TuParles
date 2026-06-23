"""Mic resolution: a configured device NAME → a PortAudio index, tolerating
hotplug. Pure logic, no audio hardware (sounddevice import is guarded)."""

from tuparles.audio import resolve_device_index

DEVICES = [
    {"index": 0, "name": "HD Webcam Mic", "default": True},
    {"index": 3, "name": "Jabra Evolve2 65", "default": False},
]


def test_empty_name_is_system_default():
    assert resolve_device_index(None, DEVICES) is None
    assert resolve_device_index("", DEVICES) is None


def test_name_resolves_to_its_index_not_position():
    # index 3, not list position 1 — indices shuffle, names don't.
    assert resolve_device_index("Jabra Evolve2 65", DEVICES) == 3


def test_disconnected_mic_degrades_to_default():
    # headset unplugged → not in the current list → None (system default),
    # never a crash and never the wrong index.
    assert resolve_device_index("Jabra Evolve2 65", []) is None
    assert resolve_device_index("Ghost Mic", DEVICES) is None
