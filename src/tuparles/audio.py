"""Microphone capture: 16 kHz mono int16, accumulated until stop().

Levels are exposed for the future waveform bubble; the demo spine only
needs start/stop/get-audio.
"""

import threading

import numpy as np
import sounddevice as sd

from tuparles.config import CHANNELS, SAMPLE_RATE


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
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=SAMPLE_RATE // 30,  # ~33 ms blocks → 30 fps levels
            callback=self._on_block,
        )
        self._stream.start()

    def _on_block(self, indata: np.ndarray, frames, time_info, status) -> None:
        with self._lock:
            self._chunks.append(indata.copy())
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        self.level = min(1.0, rms / 8000.0)

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
