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


class TestPulseSourceParsing:
    """PortAudio cannot see PipeWire sources, so the picker reads pactl instead.

    Fixtures are synthetic — a real Bluetooth address is hardware-identifying
    and has no business in a repo.
    """

    JSON = """[
      {"name": "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
       "description": "Monitor of Built-in Audio",
       "properties": {"media.class": "Audio/Sink", "device.class": "monitor"}},
      {"name": "alsa_input.pci-0000_00_1f.3.analog-stereo",
       "description": "Built-in Audio Microphone",
       "properties": {"media.class": "Audio/Source", "device.class": "sound"}},
      {"name": "bluez_input.AA_BB_CC_DD_EE_FF.0",
       "description": "Studio Headset",
       "properties": {"media.class": "Audio/Source"}}
    ]"""

    TEXT = """Source #0
\tName: alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
\tDescription: Monitor of Built-in Audio
\tProperties:
\t\tdevice.class = "monitor"
Source #1
\tName: bluez_input.AA_BB_CC_DD_EE_FF.0
\tDescription: Studio Headset
\tProperties:
\t\tdevice.class = "sound"
"""

    def test_json_keeps_real_mics_and_drops_monitors(self):
        from tuparles.pulse import parse_sources_json

        sources = parse_sources_json(self.JSON)
        assert [s["label"] for s in sources] == [
            "Built-in Audio Microphone",
            "Studio Headset",
        ]
        # The Bluetooth mic is the whole point: PortAudio never lists it.
        assert sources[-1]["name"] == "bluez_input.AA_BB_CC_DD_EE_FF.0"

    def test_text_fallback_for_pactl_without_json(self):
        from tuparles.pulse import parse_sources_text

        sources = parse_sources_text(self.TEXT)
        assert len(sources) == 1
        assert sources[0]["label"] == "Studio Headset"

    def test_garbage_and_empty_never_raise(self):
        from tuparles.pulse import parse_sources_json, parse_sources_text

        # No sound server, a truncated pipe, a pactl that printed a warning:
        # every one of these must degrade to "use the PortAudio list", not crash.
        for bad in ("", "not json", "{}", "null"):
            assert parse_sources_json(bad) == []
        assert parse_sources_text("") == []

    def test_source_without_description_falls_back_to_its_name(self):
        from tuparles.pulse import parse_sources_json

        sources = parse_sources_json('[{"name": "some.source", "properties": {}}]')
        assert sources[0]["label"] == "some.source"


class TestMicList:
    """The picker's list: pulse sources when there is a sound server, PortAudio
    devices otherwise."""

    def test_pulse_sources_win_and_carry_their_labels(self, monkeypatch):
        from tuparles import audio, pulse

        monkeypatch.setattr(
            pulse,
            "list_sources",
            lambda: [
                {
                    "name": "bluez_input.AA_BB.0",
                    "label": "Studio Headset",
                    "default": False,
                }
            ],
        )
        assert audio.list_mics() == [
            {
                "id": "bluez_input.AA_BB.0",
                "label": "Studio Headset",
                "default": False,
                "kind": "pulse",
            }
        ]

    def test_no_sound_server_falls_back_to_portaudio(self, monkeypatch):
        from tuparles import audio, pulse

        monkeypatch.setattr(pulse, "list_sources", lambda: [])
        monkeypatch.setattr(
            audio, "list_input_devices", lambda refresh=False: list(DEVICES)
        )
        mics = audio.list_mics()
        assert [m["kind"] for m in mics] == ["portaudio", "portaudio"]
        # No description to show, so the id doubles as the label.
        assert mics[1] == {
            "id": "Jabra Evolve2 65",
            "label": "Jabra Evolve2 65",
            "default": False,
            "kind": "portaudio",
        }


class TestPulseRouting:
    """Pinning a capture stream to one source, without leaking the pin."""

    def test_env_names_both_servers(self):
        from tuparles.audio import pulse_env

        env = pulse_env("bluez_input.AA_BB.0")
        # PULSE_SOURCE for libpulse, PIPEWIRE_NODE for pipewire-alsa (which
        # serves `default` and ignores the former). Same node name for both.
        assert env == {
            "PULSE_SOURCE": "bluez_input.AA_BB.0",
            "PIPEWIRE_NODE": "bluez_input.AA_BB.0",
        }

    def test_overrides_are_restored_so_a_fallback_open_is_clean(self, monkeypatch):
        import os

        from tuparles.audio import _env_overrides, pulse_env

        monkeypatch.delenv("PULSE_SOURCE", raising=False)
        with _env_overrides(pulse_env("src.0")):
            assert os.environ["PULSE_SOURCE"] == "src.0"
        # Critical: a stale pin at a headset that just walked away would make
        # the fallback re-open fail too, turning one failure into two.
        assert "PULSE_SOURCE" not in os.environ
        assert "PIPEWIRE_NODE" not in os.environ

    def test_a_pre_existing_value_survives(self, monkeypatch):
        import os

        from tuparles.audio import _env_overrides

        monkeypatch.setenv("PULSE_SOURCE", "the.user.choice")
        with _env_overrides({"PULSE_SOURCE": "ours"}):
            assert os.environ["PULSE_SOURCE"] == "ours"
        assert os.environ["PULSE_SOURCE"] == "the.user.choice"

    def test_no_env_is_a_no_op(self):
        from tuparles.audio import _env_overrides

        with _env_overrides(None):
            pass
        with _env_overrides({}):
            pass

    def test_resolution_prefers_a_pulse_source_and_pins_it(self, monkeypatch):
        from tuparles import audio, pulse, settings

        monkeypatch.setattr(settings, "get", lambda key: "bluez_input.AA_BB.0")
        # source_names(), not list_sources(): the take-start path does not need
        # the default marked, and that lookup is a second pactl call.
        monkeypatch.setattr(pulse, "source_names", lambda: {"bluez_input.AA_BB.0"})
        monkeypatch.setattr(audio, "_pulse_portaudio_index", lambda: 1)

        device, env = audio.Recorder.__new__(audio.Recorder)._resolve_input_device()
        assert device == 1
        assert env == {
            "PULSE_SOURCE": "bluez_input.AA_BB.0",
            "PIPEWIRE_NODE": "bluez_input.AA_BB.0",
        }

    def test_unknown_name_degrades_to_the_system_default(self, monkeypatch):
        from tuparles import audio, pulse, settings

        monkeypatch.setattr(settings, "get", lambda key: "a.mic.that.left")
        monkeypatch.setattr(pulse, "source_names", lambda: set())
        monkeypatch.setattr(audio, "list_input_devices", lambda refresh=False: [])

        device, env = audio.Recorder.__new__(audio.Recorder)._resolve_input_device()
        assert (device, env) == (None, {})
