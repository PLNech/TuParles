"""PipeWire/PulseAudio source enumeration, for the mics PortAudio cannot see.

PortAudio only ever shows us the ALSA world. On a PipeWire desktop that world
is two entries — `pulse` and `default` — and nothing else: a Bluetooth headset
mic is a PipeWire *source*, so `sd.query_devices()` never lists it, not even
after a rescan. The picker was therefore offering a choice between two aliases
for "whatever the desktop picked", which is no choice at all.

So we enumerate through `pactl` instead. Two things fall out of that:

- Bluetooth and USB mics appear at all, by their real names.
- We get human descriptions ("Bose QC Ultra 2 HP") instead of identifiers like
  `alsa_input.pci-0000_00_1f.3-platform-sof_sdw.HiFi__hw_sofsoundwire_4__source`.

And hotplug stops needing a rescan: pactl is queried live, so a headset paired
after launch is simply there.

Degrades, as everything here must: no `pactl`, no sound server, or a pactl too
old for `-f json` (< 15) all fall back — to the text parser first, then to the
plain PortAudio list in `audio.py`, exactly as before. Parsing lives in pure
functions so it can be tested without a sound server.
"""

import json
import shutil
import subprocess

# A PipeWire monitor (loopback of an output) is a capture source as far as the
# sound server is concerned, but nobody wants to dictate into one. The three
# markers cover PipeWire (media.class), PulseAudio proper (device.class) and
# the naming convention that has outlived both.
_MONITOR_MEDIA_CLASS = "Audio/Sink"
_MONITOR_DEVICE_CLASS = "monitor"
_MONITOR_SUFFIX = ".monitor"

_TIMEOUT = 2.0  # pactl answers in milliseconds; this is a hang guard, not a wait


def _is_monitor(name: str, props: dict) -> bool:
    return (
        name.endswith(_MONITOR_SUFFIX)
        or props.get("device.class") == _MONITOR_DEVICE_CLASS
        or props.get("media.class") == _MONITOR_MEDIA_CLASS
    )


def parse_sources_json(text: str) -> list[dict]:
    """`pactl -f json list sources` → [{name, label}], monitors dropped.

    Pure: text in, list out. `name` is the stable id we store in settings,
    `label` the human string we show in the picker.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    sources = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        props = entry.get("properties") or {}
        if _is_monitor(name, props if isinstance(props, dict) else {}):
            continue
        sources.append({"name": name, "label": entry.get("description") or name})
    return sources


def parse_sources_text(text: str) -> list[dict]:
    """Same, from plain `pactl list sources` — for pactl < 15, which has no JSON.

    Blocks open on `Source #N`; we keep the first Description of each block
    (ports carry their own further down) and watch for a monitor device.class.
    """
    sources: list[dict] = []
    name: str | None = None
    label: str | None = None
    is_monitor = False

    def flush() -> None:
        if name and not (is_monitor or name.endswith(_MONITOR_SUFFIX)):
            sources.append({"name": name, "label": label or name})

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Source #"):
            flush()
            name, label, is_monitor = None, None, False
        elif stripped.startswith("Name:"):
            name = stripped[len("Name:") :].strip()
        elif stripped.startswith("Description:") and label is None:
            label = stripped[len("Description:") :].strip()
        elif "device.class" in stripped and f'"{_MONITOR_DEVICE_CLASS}"' in stripped:
            is_monitor = True
    flush()
    return sources


def available() -> bool:
    """Is there a pactl to ask? (Absent on a bare-ALSA box, and in CI.)"""
    return shutil.which("pactl") is not None


def _run(args: list[str]) -> str | None:
    """pactl stdout, or None on any failure — a dead sound server is a
    fallback, never an exception."""
    try:
        proc = subprocess.run(
            ["pactl", *args], capture_output=True, text=True, timeout=_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def default_source_name() -> str | None:
    """The desktop's own default source, so the picker can mark it."""
    out = _run(["get-default-source"])
    return out.strip() if out and out.strip() else None


def _query_sources() -> list[dict]:
    """Real capture sources as [{name, label}]; [] when unavailable.

    One pactl call. Split out from `list_sources` because marking the default
    costs a second call, and the take-start path does not need to know which
    mic the desktop would have chosen — only whether the configured one is a
    source. That second call measured ~12 ms of the ~19 ms total, on the
    hotkey path, per take.
    """
    if not available():
        return []
    raw = _run(["-f", "json", "list", "sources"])
    sources = parse_sources_json(raw) if raw else []
    if not sources:  # pactl too old for JSON, or an empty/odd payload
        raw = _run(["list", "sources"])
        sources = parse_sources_text(raw) if raw else []
    return sources


def source_names() -> set[str]:
    """Just the source names — what resolving a stored mic actually needs."""
    return {source["name"] for source in _query_sources()}


def list_sources() -> list[dict]:
    """Real capture sources as [{name, label, default}]; [] when unavailable.

    For the picker, which does want the default marked. Queried live — no
    snapshot to invalidate, so a mic paired thirty seconds ago is already in
    the list.
    """
    sources = _query_sources()
    if not sources:
        return []
    default = default_source_name()
    for source in sources:
        source["default"] = source["name"] == default
    return sources
