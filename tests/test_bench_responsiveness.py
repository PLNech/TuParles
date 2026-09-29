"""Regressions for the public-audio responsiveness harness."""

import runpy
from pathlib import Path

import pytest


@pytest.fixture
def bench():
    pytest.importorskip("PySide6")
    path = Path(__file__).resolve().parents[1] / "scripts" / "bench_responsiveness.py"
    return runpy.run_path(str(path))


class FakeApp:
    def processEvents(self) -> None:
        pass


class FakeHeartbeat:
    def reset(self) -> None:
        pass

    def report(self, _label: str) -> dict:
        return {"ticks": 1}


def test_gpu_run_reads_transcription_text(bench, monkeypatch):
    from tuparles import engine
    from tuparles.transcription import Transcription

    class FakeGpu:
        def transcribe(self, _audio):
            return Transcription("public synthetic words")

    monkeypatch.setattr(engine, "GpuEngine", FakeGpu)
    monkeypatch.setitem(bench["gpu_run"].__globals__, "load_take", lambda _s: [0] * 4)
    runs = bench["gpu_run"](FakeApp(), FakeHeartbeat(), [1])
    assert runs[0]["chars"] == len("public synthetic words")


def test_gpu_worker_exception_finishes_instead_of_hanging(bench, monkeypatch):
    from tuparles import engine

    class BrokenGpu:
        def transcribe(self, _audio):
            raise ValueError("synthetic decode failure")

    monkeypatch.setattr(engine, "GpuEngine", BrokenGpu)
    monkeypatch.setitem(bench["gpu_run"].__globals__, "load_take", lambda _s: [0] * 4)
    with pytest.raises(RuntimeError, match="synthetic decode failure"):
        bench["gpu_run"](FakeApp(), FakeHeartbeat(), [1])
