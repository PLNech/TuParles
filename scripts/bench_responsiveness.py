"""Measure GUI-thread starvation during decode — numbers, not vibes.

Replicates the daemon's threading: Qt event loop on the main thread, engine
decode in a worker. A 33 ms QTimer heartbeat runs throughout; any gap well
above 33 ms means the GUI thread was starved (GIL or otherwise) and clicks,
animations, and the tray menu would freeze for that long.

Usage: QT_QPA_PLATFORM=offscreen poetry run python scripts/bench_responsiveness.py
"""

import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "vendor" / "qwen-asr" / "samples" / "jfk.wav"
TARGET_S = 66


def load_take() -> np.ndarray:
    with wave.open(str(SAMPLE), "rb") as w:
        rate = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    reps = int(TARGET_S * rate / len(audio)) + 1
    return np.tile(audio, reps)[: TARGET_S * rate]


class Heartbeat:
    def __init__(self) -> None:
        self.gaps: list[float] = []
        self._last = time.monotonic()
        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        self.gaps.append(now - self._last)
        self._last = now

    def report(self, label: str) -> None:
        gaps = np.array(self.gaps)
        bad = gaps[gaps > 0.1]
        print(
            f"  [{label}] ticks={len(gaps)} max_gap={gaps.max() * 1000:.0f}ms "
            f"p99={np.percentile(gaps, 99) * 1000:.0f}ms "
            f"gaps>100ms={len(bad)} (total starved {bad.sum():.1f}s)"
        )
        self.gaps.clear()
        self._last = time.monotonic()


def main() -> None:
    app = QApplication(sys.argv)
    audio = load_take()
    print(f"take: {len(audio) / 16000:.0f}s of tiled JFK")

    print("loading engine…")
    from tuparles.engine import GpuEngine

    engine = GpuEngine()
    hb = Heartbeat()

    scenarios = [
        ("batched (current)", lambda: engine.transcribe(audio)),
        ("sequential (pre-fix)", lambda: _sequential(engine, audio)),
    ]
    for label, fn in scenarios:
        for switch_interval in (0.005, 0.0005):
            sys.setswitchinterval(switch_interval)
            done = threading.Event()
            result = {}

            def work(fn=fn, result=result, done=done):
                t0 = time.monotonic()
                result["text_len"] = len(fn())
                result["wall"] = time.monotonic() - t0
                done.set()

            hb.gaps.clear()
            hb._last = time.monotonic()
            threading.Thread(target=work, daemon=True).start()
            while not done.is_set():
                app.processEvents()
                time.sleep(0.001)
            print(
                f"{label} | switchinterval={switch_interval}: "
                f"decode {result['wall']:.1f}s, {result['text_len']} chars"
            )
            hb.report("during decode")


def _sequential(engine, audio: np.ndarray) -> str:
    pcm = audio.astype(np.float32) / 32768.0
    segments, _ = engine._model.transcribe(
        pcm, beam_size=5, vad_filter=True, initial_prompt=engine._prompt
    )
    return " ".join(s.text.strip() for s in segments).strip()


if __name__ == "__main__":
    main()
