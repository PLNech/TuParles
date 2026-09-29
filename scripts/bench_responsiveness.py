"""Exercise Qt responsiveness without a microphone, hotkey, or real delivery.

Controller mode uses synthetic audio and a delayed fake engine to measure queue
cadence and stop-to-delivery while opening Analytics over a temporary 2,000-row
history. Controller-GPU mode uses the real engine with the same safe stubs.
GPU mode decodes the bundled public JFK sample on the real engine.

Run GPU mode under ``flock /tmp/tuparles-inference-bench.lock`` when other
inference benchmarks may be active. The reported delivery is a stub callback,
not clipboard/paste or physical hotkey latency.

Usage:
  QT_QPA_PLATFORM=offscreen poetry run python scripts/bench_responsiveness.py --mode controller
  QT_QPA_PLATFORM=offscreen flock /tmp/tuparles-inference-bench.lock poetry run python scripts/bench_responsiveness.py --mode controller-gpu --json-out /tmp/tuparles_responsiveness_gpu.json
  QT_QPA_PLATFORM=offscreen flock /tmp/tuparles-inference-bench.lock poetry run python scripts/bench_responsiveness.py --mode gpu
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import wave
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "vendor" / "qwen-asr" / "samples" / "jfk.wav"
RATE = 16000


def load_take(seconds: float) -> np.ndarray:
    """Tile a public, bundled speech sample; never read personal history/audio."""
    with wave.open(str(SAMPLE), "rb") as wav:
        assert wav.getframerate() == RATE and wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    reps = int(seconds * RATE / len(audio)) + 1
    return np.tile(audio, reps)[: int(seconds * RATE)]


class Heartbeat:
    def __init__(self) -> None:
        self.gaps_ms: list[float] = []
        self._last = time.monotonic()
        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        self.gaps_ms.append((now - self._last) * 1000)
        self._last = now

    def reset(self) -> None:
        self.gaps_ms.clear()
        self._last = time.monotonic()

    def report(self, label: str) -> dict[str, float | int]:
        gaps = np.asarray(self.gaps_ms)
        if not gaps.size:
            print(f"{label}: no heartbeat ticks")
            return {"ticks": 0, "max_ms": 0.0, "p99_ms": 0.0, "over_100ms": 0}
        summary = {
            "ticks": len(gaps),
            "max_ms": round(float(gaps.max()), 1),
            "p99_ms": round(float(np.percentile(gaps, 99)), 1),
            "over_100ms": int((gaps > 100).sum()),
        }
        print(
            f"{label}: ticks={summary['ticks']}, max={summary['max_ms']:.0f}ms, "
            f"p99={summary['p99_ms']:.0f}ms, >100ms={summary['over_100ms']}"
        )
        return summary


def pump_until(app: QApplication, condition, timeout_s: float = 30) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("benchmark condition did not complete")
        time.sleep(0.001)
    app.processEvents()


def seed_history(rows: int = 2000) -> None:
    from tuparles import history

    # The environment is redirected to TemporaryDirectory before this call.
    with history._conn() as conn:
        conn.executemany(
            "INSERT INTO dictations (ts, text, engine) VALUES (?, ?, ?)",
            (
                (
                    "2026-01-01T00:00:00",
                    f"Bonjour, analyse de la fonction numéro {i}.",
                    "bench",
                )
                for i in range(rows)
            ),
        )


class FakeRecorder:
    def __init__(self, audio: np.ndarray, stop_delay_s: float = 0.05) -> None:
        self.audio = audio
        self.stop_delay_s = stop_delay_s
        self.recording = False

    def start(self) -> None:
        self.recording = True

    def stop(self) -> np.ndarray:
        time.sleep(self.stop_delay_s)
        self.recording = False
        return self.audio.copy()

    def snapshot(self, max_samples: int | None = None) -> np.ndarray:
        return self.audio[-max_samples:].copy() if max_samples else self.audio.copy()


class FakeBubble:
    def start_recording(self) -> None:
        pass

    def start_processing(self) -> None:
        pass

    def cancel(self) -> None:
        pass


class FakeEngine:
    supports_partials = False
    active_backend = "gpu"

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    def transcribe(self, _audio: np.ndarray, _context=None):
        from tuparles.transcription import Transcription

        time.sleep(self.delay_s)
        return Transcription("Bonjour, ceci est un résultat synthétique.")

    def transcribe_partial(self, _audio: np.ndarray) -> str:
        return "aperçu synthétique"


def controller_run(app: QApplication, heartbeat: Heartbeat) -> dict:
    from tuparles import daemon
    from tuparles.telemetry_dashboard import AnalyticsDialog

    seed_history()
    audio = np.ones(RATE, dtype=np.int16)
    recorder = FakeRecorder(audio)
    bridge = daemon.Bridge()
    delivered_at: dict[int, float] = {}
    stop_at: dict[int, float] = {}
    queued_at: dict[int, float] = {}
    ui_errors: list[str] = []
    preview_at: list[float] = []
    bridge.queued.connect(lambda seq: queued_at.__setitem__(seq, time.monotonic()))
    bridge.delivered.connect(
        lambda seq: delivered_at.__setitem__(seq, time.monotonic())
    )
    bridge.error.connect(ui_errors.append)
    bridge.partial.connect(lambda _text: preview_at.append(time.monotonic()))
    # No focus probing, click sounds, clipboard, paste, or real user-history writes.
    real_get = daemon.settings.get
    overrides = {
        "queue_depth_cap": 4,
        "trim_silence": False,
        "context_carryover": False,
        "context_carryover_window_s": 0,
        "context_carryover_max_chars": 0,
        "deliver_to": "current",
        "backend_toast": False,
    }
    with (
        patch.object(daemon.mapping_canary, "start"),
        patch.object(daemon.mapping_canary, "count", return_value=0),
        patch.object(daemon.mapping_canary, "enabled", return_value=False),
        patch.object(daemon, "capture_target", return_value=daemon.DeliveryTarget()),
        patch.object(daemon.cue, "play_start"),
        patch.object(daemon, "IS_WAYLAND", False),
        patch.object(daemon.Controller, "_deliver"),
        patch.object(
            daemon.settings,
            "get",
            side_effect=lambda k: overrides[k] if k in overrides else real_get(k),
        ),
    ):
        controller = daemon.Controller(FakeEngine(0.5), recorder, FakeBubble(), bridge)
        bridge.preview_candidate.connect(controller._publish_partial)
        controller.start()
        heartbeat.reset()
        controller.toggle_from_hotkey()  # arm take 1
        stop_at[1] = time.monotonic()
        controller.toggle_from_hotkey()  # stop take 1; teardown on worker
        pump_until(app, lambda: not controller._stopping, 5)
        controller.toggle_from_hotkey()  # arm take 2 before take 1 delivers
        restarted_at = time.monotonic()
        restarted_before_delivery = 1 not in delivered_at
        analytics_open_at = time.monotonic()
        dialog = AnalyticsDialog()
        dialog.show()
        dialog._tabs.setCurrentIndex(1)  # real NLP on synthetic 2,000 rows
        stop_at[2] = time.monotonic()
        controller.toggle_from_hotkey()  # stop take 2 during Analytics work
        pump_until(app, lambda: "Ta voix" in dialog._views[1].toPlainText(), 30)
        analytics_first_content_at = time.monotonic()
        pump_until(app, lambda: 1 in dialog._loaded, 30)
        analytics_loaded_at = time.monotonic()
        pump_until(app, lambda: len(delivered_at) == 2, 30)
        dialog.close()
        responsiveness = heartbeat.report("Controller + Analytics")
        print(f"restarted_before_first_delivery={restarted_before_delivery}")
        print(f"stop-to-restart={(restarted_at - stop_at[1]) * 1000:.0f}ms")
        print(
            f"Analytics open-to-voice-loaded={(analytics_loaded_at - analytics_open_at) * 1000:.0f}ms"
        )
        print(f"queued_order={list(queued_at)}, delivered_order={list(delivered_at)}")
        for seq in (1, 2):
            print(
                f"take {seq}: stop-to-queued={(queued_at[seq] - stop_at[seq]) * 1000:.0f}ms, "
                f"stop-to-delivered={(delivered_at[seq] - stop_at[seq]) * 1000:.0f}ms"
            )
        print(f"errors={ui_errors}")
        assert restarted_before_delivery and list(delivered_at) == [1, 2]
        assert not ui_errors
        # Measure preview cadence separately: the decode above has partials
        # disabled, while this third synthetic take exercises the timer loop.
        controller._engine.supports_partials = True
        controller.toggle_from_hotkey()
        pump_until(app, lambda: len(preview_at) >= 3, 10)
        controller.cancel()
        pump_until(app, lambda: not controller._stopping, 5)
        intervals_ms = [round((b - a) * 1000, 1) for a, b in pairwise(preview_at)]
        print(f"synthetic preview intervals={intervals_ms}")
        controller._decode_q.put(None)
        controller._decode_q.join()
        return {
            "heartbeat": responsiveness,
            "restarted_before_first_delivery": restarted_before_delivery,
            "stop_to_restart_ms": round((restarted_at - stop_at[1]) * 1000, 1),
            "analytics_first_content_ms": round(
                (analytics_first_content_at - analytics_open_at) * 1000, 1
            ),
            "analytics_voice_load_ms": round(
                (analytics_loaded_at - analytics_open_at) * 1000, 1
            ),
            "queued_order": list(queued_at),
            "delivered_order": list(delivered_at),
            "stop_to_queued_ms": {
                seq: round((queued_at[seq] - stop_at[seq]) * 1000, 1) for seq in (1, 2)
            },
            "stop_to_delivered_ms": {
                seq: round((delivered_at[seq] - stop_at[seq]) * 1000, 1)
                for seq in (1, 2)
            },
            "synthetic_preview_intervals_ms": intervals_ms,
            "errors": ui_errors,
        }


def controller_gpu_run(app: QApplication, heartbeat: Heartbeat) -> dict:
    """Real preview/final decode with fake capture and intercepted delivery."""
    from tuparles import daemon
    from tuparles.engine import GpuEngine
    from tuparles.telemetry_dashboard import AnalyticsDialog

    seed_history()
    print("loading GPU engine for Controller…", flush=True)
    engine = GpuEngine()
    recorder = FakeRecorder(load_take(8))
    bridge = daemon.Bridge()
    preview_started = threading.Event()
    preview_active = threading.Event()
    preview_decode_ms: list[float] = []
    preview_at: list[float] = []
    stop_at: dict[int, float] = {}
    queued_at: dict[int, float] = {}
    stub_at: dict[int, float] = {}
    delivered_at: dict[int, float] = {}
    errors: list[str] = []
    real_partial = engine.transcribe_partial

    def observed_partial(audio: np.ndarray) -> str:
        preview_active.set()
        preview_started.set()
        started = time.monotonic()
        try:
            return real_partial(audio)
        finally:
            preview_decode_ms.append((time.monotonic() - started) * 1000)
            preview_active.clear()

    engine.transcribe_partial = observed_partial
    bridge.queued.connect(lambda seq: queued_at.__setitem__(seq, time.monotonic()))
    bridge.delivered.connect(
        lambda seq: delivered_at.__setitem__(seq, time.monotonic())
    )
    bridge.partial.connect(lambda _text: preview_at.append(time.monotonic()))
    bridge.error.connect(errors.append)

    def stub_deliver(_self, _text, _target, seq) -> None:
        stub_at[seq] = time.monotonic()

    real_get = daemon.settings.get
    # Retain real defaults for GPU language/conditioning and every unspecified
    # setting. Only make benchmark duration and destination deterministic.
    overrides = {"trim_silence": False, "deliver_to": "current"}
    with (
        patch.object(daemon.mapping_canary, "start"),
        patch.object(daemon.mapping_canary, "count", return_value=0),
        patch.object(daemon.mapping_canary, "enabled", return_value=False),
        patch.object(daemon, "capture_target", return_value=daemon.DeliveryTarget()),
        patch.object(daemon.cue, "play_start"),
        patch.object(daemon, "IS_WAYLAND", False),
        patch.object(daemon.Controller, "_deliver", stub_deliver),
        patch.object(
            daemon.settings,
            "get",
            side_effect=lambda k: overrides[k] if k in overrides else real_get(k),
        ),
    ):
        controller = daemon.Controller(engine, recorder, FakeBubble(), bridge)
        bridge.preview_candidate.connect(controller._publish_partial)
        controller.start()
        heartbeat.reset()
        controller.toggle_from_hotkey()
        pump_until(app, preview_started.is_set, 30)
        stopped_during_preview = preview_active.is_set()
        stop_at[1] = time.monotonic()
        controller.toggle_from_hotkey()
        pump_until(app, lambda: not controller._stopping, 10)
        controller.toggle_from_hotkey()
        restarted_at = time.monotonic()
        restarted_before_delivery = 1 not in stub_at

        analytics_open_at = time.monotonic()
        dialog = AnalyticsDialog()
        dialog.show()
        dialog._tabs.setCurrentIndex(1)
        pump_until(app, lambda: len(preview_at) >= 2, 90)
        stop_at[2] = time.monotonic()
        controller.toggle_from_hotkey()
        pump_until(app, lambda: 1 in dialog._loaded, 90)
        analytics_loaded_at = time.monotonic()
        pump_until(app, lambda: len(delivered_at) == 2, 120)
        dialog.close()
        responsiveness = heartbeat.report("Controller GPU + Analytics")
        intervals_ms = [round((b - a) * 1000, 1) for a, b in pairwise(preview_at)]
        result = {
            "heartbeat": responsiveness,
            "stopped_during_real_preview": stopped_during_preview,
            "restarted_before_first_stub_delivery": restarted_before_delivery,
            "stop_to_restart_ms": round((restarted_at - stop_at[1]) * 1000, 1),
            "analytics_voice_load_ms": round(
                (analytics_loaded_at - analytics_open_at) * 1000, 1
            ),
            "queued_order": list(queued_at),
            "stub_delivery_order": list(stub_at),
            "delivered_signal_order": list(delivered_at),
            "stop_to_stub_delivery_ms": {
                seq: round((stub_at[seq] - stop_at[seq]) * 1000, 1) for seq in (1, 2)
            },
            "real_preview_decode_ms": [round(v, 1) for v in preview_decode_ms],
            "real_preview_intervals_ms": intervals_ms,
            "errors": errors,
        }
        print("Controller GPU metrics=" + json.dumps(result, sort_keys=True))
        controller._decode_q.put(None)
        controller._decode_q.join()
        assert stopped_during_preview and restarted_before_delivery
        assert list(queued_at) == list(stub_at) == list(delivered_at) == [1, 2]
        assert not errors
        return result


def gpu_run(
    app: QApplication, heartbeat: Heartbeat, durations: list[float]
) -> list[dict]:
    from tuparles.engine import GpuEngine

    print("loading GPU engine…", flush=True)
    engine = GpuEngine()
    runs = []
    for seconds in durations:
        audio = load_take(seconds)
        done = threading.Event()
        result: dict[str, object] = {}

        def work(audio=audio, result=result, done=done) -> None:
            started = time.monotonic()
            try:
                transcript = engine.transcribe(audio)
                result["chars"] = len(transcript.text)
            except Exception as exc:
                result["error"] = repr(exc)
            finally:
                result["wall_s"] = time.monotonic() - started
                done.set()

        heartbeat.reset()
        threading.Thread(target=work, daemon=True).start()
        pump_until(app, done.is_set, max(120, seconds * 5))
        if "error" in result:
            raise RuntimeError(f"GPU decode failed: {result['error']}")
        print(
            f"GPU {seconds:g}s public audio: decode={result['wall_s']:.2f}s, "
            f"chars={result['chars']}"
        )
        runs.append(
            {
                "audio_s": seconds,
                "decode_s": round(float(result["wall_s"]), 2),
                "chars": result["chars"],
                "heartbeat": heartbeat.report("during GPU decode"),
            }
        )
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("controller", "controller-gpu", "gpu", "all"),
        default="controller",
    )
    parser.add_argument(
        "--durations", default="8,66", help="GPU take lengths in seconds"
    )
    parser.add_argument("--json-out", type=Path, help="write aggregate metrics as JSON")
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Preserve the existing model cache before XDG_CACHE_HOME is isolated;
    # never download a model as a side effect of this benchmark.
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("HF_HUB_CACHE", str(hf_home / "hub"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    with tempfile.TemporaryDirectory(prefix="tuparles-bench-") as tmp:
        os.environ["XDG_DATA_HOME"] = str(Path(tmp) / "data")
        os.environ["XDG_CONFIG_HOME"] = str(Path(tmp) / "config")
        os.environ["XDG_CACHE_HOME"] = str(Path(tmp) / "cache")
        os.environ["TUPARLES_CONFIG_DIR"] = str(Path(tmp) / "config" / "tuparles")
        app = QApplication(sys.argv[:1])
        heartbeat = Heartbeat()
        results = {}
        if args.mode in ("controller", "all"):
            results["controller"] = controller_run(app, heartbeat)
        if args.mode in ("controller-gpu", "all"):
            results["controller_gpu"] = controller_gpu_run(app, heartbeat)
        if args.mode in ("gpu", "all"):
            results["gpu"] = gpu_run(
                app, heartbeat, [float(s) for s in args.durations.split(",")]
            )
        print("RESULT_JSON=" + json.dumps(results, sort_keys=True))
        if args.json_out:
            args.json_out.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n"
            )


if __name__ == "__main__":
    main()
