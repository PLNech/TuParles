"""Microphone capture: 16 kHz mono int16, accumulated until stop().

Levels are exposed for the future waveform bubble; the demo spine only
needs start/stop/get-audio.

Device selection: the chosen mic is stored by NAME (settings "input_device";
empty = system default). Names are stable where PortAudio indices are not —
plug in a Bluetooth headset and every index after it shifts. We re-resolve
the name to an index at each take, and if the device has vanished (headset
disconnected mid-session) we fall back to the default rather than kill a take.
"""

import threading

import numpy as np

try:
    import sounddevice as sd
except (OSError, ImportError):  # no libportaudio (e.g. CI) — pure helpers still import
    sd = None

from tuparles import settings
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
        device = self._resolve_input_device()
        try:
            self._stream = self._open(device)
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

    def _open(self, device):
        return sd.InputStream(
            device=device,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=SAMPLE_RATE // 30,  # ~33 ms blocks → 30 fps levels
            callback=self._on_block,
        )

    def _resolve_input_device(self):
        """Index for the configured mic name, or None (system default). Names
        are stable across hotplug where indices are not; if the name isn't in
        the current list it may have just been plugged in — rescan once."""
        name = settings.get("input_device")
        if not name:
            return None
        idx = resolve_device_index(name, list_input_devices())
        if idx is None:
            idx = resolve_device_index(name, list_input_devices(refresh=True))
        return idx

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

    def snapshot(self) -> np.ndarray:
        """Copy of everything captured so far, without stopping.

        Feeds the live-partials loop: the GPU re-decodes this growing
        buffer ~1x/s while the user keeps talking.
        """
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(self._chunks).reshape(-1)

    def stop(self) -> np.ndarray:
        """Stop capture and return the whole take as int16 mono."""
        if self._stream is None:
            return np.zeros(0, dtype=np.int16)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.int16)
            audio = np.concatenate(self._chunks).reshape(-1)
            self._chunks = []
        return audio
