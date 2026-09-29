"""Microphone capture: 16 kHz mono int16, accumulated until stop().

Levels are exposed for the future waveform bubble; the demo spine only
needs start/stop/get-audio.

Device selection: the chosen mic is stored by NAME (settings "input_device";
empty = system default). Names are stable where PortAudio indices are not —
plug in a Bluetooth headset and every index after it shifts. We re-resolve
the name to an index at each take, and if the device has vanished (headset
disconnected mid-session) we fall back to the default rather than kill a take.

Two worlds of names, in preference order (see `list_mics`):

- **PipeWire/PulseAudio source names** (`pulse.list_sources()`) when a sound
  server is running. This is the only way a Bluetooth mic is selectable at all
  — PortAudio does not enumerate PipeWire sources. Routing to one is done by
  opening PortAudio's `pulse`/`default` device with PULSE_SOURCE and
  PIPEWIRE_NODE pinned to the source name for the duration of the open.
- **PortAudio device names**, the original path, for a bare-ALSA box or CI.

A stored name is looked up in that order, so settings written before the
PipeWire path existed keep resolving. Unknown in both → system default.
"""

import contextlib
import os
import threading
import time

import numpy as np

try:
    import sounddevice as sd
except (OSError, ImportError):  # no libportaudio (e.g. CI) — pure helpers still import
    sd = None

from tuparles import pulse, settings
from tuparles.config import (
    CHANNELS,
    LEVEL_FULL_SCALE,
    LEVEL_GAMMA,
    LEVEL_NOISE_FLOOR,
    SAMPLE_RATE,
)


def _refresh_portaudio() -> None:
    """Rescan devices so a just-(dis)connected Bluetooth/USB headset is seen
    without restarting the daemon. PortAudio snapshots its device list at
    init, so we bounce it. Best-effort — never raise from a device rescan."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def list_input_devices(refresh: bool = False) -> list[dict]:
    """Input-capable devices as {index, name, default}. refresh=True forces
    a PortAudio rescan (used by the settings dialog so hotplugged mics show)."""
    if refresh:
        _refresh_portaudio()
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = -1
    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            devices.append(
                {"index": idx, "name": dev["name"], "default": idx == default_in}
            )
    return devices


def resolve_device_index(name, devices) -> int | None:
    """PortAudio index for a stored device NAME among `devices`. Returns None
    (= system default) when the name is empty or no longer present — a
    disconnected headset must degrade to the default mic, never crash."""
    if not name:
        return None
    for dev in devices:
        if dev["name"] == name:
            return dev["index"]
    return None


def list_mics(refresh: bool = False) -> list[dict]:
    """The picker's list: [{id, label, default, kind}], best source available.

    Prefers PipeWire/Pulse sources — they include Bluetooth mics and carry
    human labels ("Bose QC Ultra 2 HP"). Falls back to PortAudio devices, whose
    name doubles as the label because that is all we have. `id` is what goes
    into settings; `refresh` only means anything to the PortAudio path (pactl
    is queried live and needs no rescan).
    """
    sources = pulse.list_sources()
    if sources:
        return [
            {
                "id": source["name"],
                "label": source["label"],
                "default": source.get("default", False),
                "kind": "pulse",
            }
            for source in sources
        ]
    return [
        {
            "id": dev["name"],
            "label": dev["name"],
            "default": dev["default"],
            "kind": "portaudio",
        }
        for dev in list_input_devices(refresh=refresh)
    ]


def pulse_env(source_name: str) -> dict:
    """Env that pins a capture stream to one PipeWire/Pulse source.

    PULSE_SOURCE is honoured by libpulse (the ALSA `pulse` plugin passes no
    explicit source, so the env wins); PIPEWIRE_NODE covers pipewire-alsa,
    which serves `default` and ignores PULSE_SOURCE. The source name is the
    node name, so one value feeds both.
    """
    return {"PULSE_SOURCE": source_name, "PIPEWIRE_NODE": source_name}


def _pulse_portaudio_index() -> int | None:
    """Index of the PortAudio device that fronts the sound server, or None.

    `pulse` first, `default` as the runner-up — never hardcoded, since which
    of them exists varies by box.
    """
    devices = {dev["name"]: dev["index"] for dev in list_input_devices()}
    for candidate in ("pulse", "default"):
        if candidate in devices:
            return devices[candidate]
    return None


@contextlib.contextmanager
def _env_overrides(env: dict | None):
    """Apply env vars for the block, then restore exactly what was there.

    Scope matters twice over. The ALSA plugin connects to the sound server
    inside the `InputStream` *constructor*, so the vars must be set around
    construction, not around `start()`. And restoring them means the
    fallback re-open can never inherit a PULSE_SOURCE pointing at a headset
    that just walked out of range — which would turn "degrade to the default
    mic" into a second failure.
    """
    if not env:
        yield
        return
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for key, previous in saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


class Recorder:
    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self.level: float = 0.0  # rolling RMS in [0, 1], for the waveform UI

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks = []
        device, env = self._resolve_input_device()
        try:
            self._stream = self._open(device, env)
            self._stream.start()
        except Exception:
            # Chosen mic gone (Bluetooth dropped between takes?) — rescan and
            # retry on the system default so a take never dies on a missing
            # device. None = PortAudio default.
            if self._stream is not None:
                self._stream.close()
            _refresh_portaudio()
            self._stream = self._open(None)
            self._stream.start()
            print("micro choisi indisponible — micro par défaut")

    def _open(self, device, env: dict | None = None):
        with _env_overrides(env):
            return sd.InputStream(
                device=device,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=SAMPLE_RATE // 30,  # ~33 ms blocks → 30 fps levels
                callback=self._on_block,
            )

    def _resolve_input_device(self):
        """(PortAudio device, env overrides) for the configured mic.

        A PipeWire/Pulse source resolves to the server's PortAudio device plus
        the env that pins it to that source. Otherwise we fall back to the
        original PortAudio name lookup — names are stable across hotplug where
        indices are not, and if the name isn't in the current list it may have
        just been plugged in, so rescan once. (None, {}) = system default, the
        answer for a mic that is no longer anywhere to be found.
        """
        name = settings.get("input_device")
        if not name:
            return None, {}
        if name in pulse.source_names():  # one pactl call, no default lookup
            index = _pulse_portaudio_index()
            if index is not None:
                return index, pulse_env(name)
        idx = resolve_device_index(name, list_input_devices())
        if idx is None:
            idx = resolve_device_index(name, list_input_devices(refresh=True))
        return idx, {}

    def _on_block(self, indata: np.ndarray, frames, time_info, status) -> None:
        with self._lock:
            self._chunks.append(indata.copy())
        # Perceptual mapping (see config): gate out silence, scale to a
        # speech-typical peak, gamma-lift so quiet/mid speech still moves bars.
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        norm = max(
            0.0, (rms - LEVEL_NOISE_FLOOR) / (LEVEL_FULL_SCALE - LEVEL_NOISE_FLOOR)
        )
        self.level = min(1.0, norm**LEVEL_GAMMA)

    def snapshot(self, max_samples: int | None = None) -> np.ndarray:
        """Copy the capture, optionally limited to its latest mono samples.

        Only references to the callback-owned chunks are gathered under the
        lock. The potentially expensive concatenation happens after the
        callback can resume. A bounded snapshot walks backward from the newest
        chunk, so its work depends on the requested window rather than the
        length of the take.
        """
        if max_samples is not None and max_samples < 0:
            raise ValueError("max_samples must be non-negative")
        if max_samples == 0:
            return np.zeros(0, dtype=np.int16)
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.int16)
            if max_samples is None:
                chunks = self._chunks.copy()
            else:
                chunks = []
                remaining = max_samples
                for chunk in reversed(self._chunks):
                    chunks.append(chunk)
                    remaining -= chunk.size
                    if remaining <= 0:
                        break
                chunks.reverse()
        audio = np.concatenate(chunks).reshape(-1)
        return audio if max_samples is None else audio[-max_samples:]

    def stop(self) -> np.ndarray:
        """Stop capture and return the whole take as int16 mono.

        The daemon times the whole call as ``stop_s``; once (id 162) it took
        65 s while the decode was 1 s — an *episodic* PortAudio teardown stall
        (NOT length-driven: a longer take, id 157, stopped in 0.03 s). It can't
        be reproduced from a captured WAV (replay bypasses the recorder), so we
        instrument the three sub-steps and shout the breakdown only when the
        call is slow — silent on every normal take, a fingerprint on the stall.
        """
        if self._stream is None:
            return np.zeros(0, dtype=np.int16)
        t0 = time.monotonic()
        self._stream.stop()
        t_stop = time.monotonic()
        self._stream.close()
        t_close = time.monotonic()
        self._stream = None
        with self._lock:
            audio = (
                np.concatenate(self._chunks).reshape(-1)
                if self._chunks
                else np.zeros(0, dtype=np.int16)
            )
            self._chunks = []
        t_concat = time.monotonic()
        if t_concat - t0 > 0.5:  # a normal stop is ~milliseconds; this is a stall
            print(
                f"recorder.stop slow: pa_stop {t_stop - t0:.2f}s, "
                f"pa_close {t_close - t_stop:.2f}s, "
                f"concat {t_concat - t_close:.2f}s"
            )
        return audio
