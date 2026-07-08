"""Offline file-transcription helpers (`tuparles transcribe`). Model-free: we
test the ffmpeg decode, the timestamp/render formatting, and device selection —
the actual Whisper decode is covered by the live daemon/eval paths."""

from pathlib import Path

import pytest

from tuparles import filetranscribe as ft

REPO_ROOT = Path(__file__).resolve().parents[1]
SPIKE_WAV = REPO_ROOT / "spike-test.wav"


def test_format_ts_minutes_and_hours():
    assert ft.format_ts(9) == "00:09"
    assert ft.format_ts(75) == "01:15"
    assert ft.format_ts(3725) == "1:02:05"  # rolls over to h:mm:ss past the hour


def test_pick_device_cpu_is_int8_small():
    assert ft.pick_device("cpu") == ("cpu", "int8", ft.CPU_FILE_MODEL)


def test_pick_device_explicit_cuda_is_turbo_float16():
    assert ft.pick_device("cuda") == ("cuda", "float16", "large-v3-turbo")


def test_render_applies_lexicon_and_skips_empty_segments():
    segs = [
        ft.Segment(0.0, 2.0, "bonjour"),
        ft.Segment(2.0, 4.0, ""),  # empty → no line
        ft.Segment(4.0, 6.0, "monde"),
    ]
    out = ft.render_transcript(
        segs, source="x.m4a", model="m", device="cpu", duration=75.0, date="2026-07-08"
    )
    lines = out.splitlines()
    assert lines[0] == "# x.m4a  ·  01:15  ·  m (cpu)  ·  2026-07-08"
    assert lines[1] == ""
    body = [line for line in lines[2:] if line]
    assert body == ["[00:00] bonjour", "[00:04] monde"]  # empty middle dropped


@pytest.mark.skipif(not SPIKE_WAV.exists(), reason="spike-test.wav absent")
def test_decode_to_pcm_resamples_to_float32_mono_16k():
    import numpy as np

    pcm = ft.decode_to_pcm(SPIKE_WAV)
    assert pcm.dtype == np.float32
    assert pcm.ndim == 1  # downmixed to mono
    assert len(pcm) / ft.SAMPLE_RATE > 1.0  # a few seconds of audio


def test_decode_to_pcm_missing_ffmpeg_raises_human_message(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(ft.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="ffmpeg introuvable"):
        ft.decode_to_pcm(Path("nope.m4a"))


# --- device probing (ct2, not torch) ------------------------------------


def _poison_torch(monkeypatch):
    """Inject a torch stub that detonates on any attribute access, so a test
    proves `pick_device` reaches the ct2 probe and never touches torch."""
    import sys
    import types

    class _Poison(types.ModuleType):
        def __getattr__(self, name):
            raise AssertionError("torch must not be used")

    monkeypatch.setitem(sys.modules, "torch", _Poison("torch"))


def test_pick_device_auto_uses_ctranslate2_not_torch_cpu(monkeypatch):
    import ctranslate2

    _poison_torch(monkeypatch)
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    assert ft.pick_device("auto") == ("cpu", "int8", ft.CPU_FILE_MODEL)


def test_pick_device_auto_uses_ctranslate2_not_torch_cuda(monkeypatch):
    import ctranslate2

    _poison_torch(monkeypatch)
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    assert ft.pick_device("auto") == ("cuda", "float16", "large-v3-turbo")


# --- decode-time GPU-wedge fallback --------------------------------------


class _FakeSeg:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class _FakeBatchedOK:
    """A working batched pipeline yielding a couple of fake segments."""

    def transcribe(self, pcm, **kw):
        segs = [_FakeSeg(0.0, 1.0, " bonjour "), _FakeSeg(1.0, 2.0, " monde ")]
        return iter(segs), object()


class _FakeBatchedWedged:
    """A CUDA context that loaded fine but throws on decode (suspend/resume)."""

    def transcribe(self, pcm, **kw):
        raise RuntimeError("CUDA failed with error out of memory")


def _bare_transcriber(monkeypatch, *, device, batched, model_override=None):
    """A FileTranscriber built without loading real models. Keeps the decode
    hermetic: no user glossary, no language config."""
    monkeypatch.setattr(ft.settings, "get", lambda *a, **k: [])
    monkeypatch.setattr(ft, "_vocab_prompt", lambda: None)
    t = ft.FileTranscriber.__new__(ft.FileTranscriber)
    t.device = device
    t.model_name = "large-v3-turbo" if device == "cuda" else ft.CPU_FILE_MODEL
    t._model_override = model_override
    t._batched = batched
    return t


def test_decode_wedge_on_cuda_falls_back_to_cpu(monkeypatch, capsys):
    t = _bare_transcriber(monkeypatch, device="cuda", batched=_FakeBatchedWedged())

    def fake_load(self, dev, compute, model_name):
        self.device = dev
        self.model_name = model_name
        self._batched = _FakeBatchedOK()

    monkeypatch.setattr(ft.FileTranscriber, "_load", fake_load)

    import numpy as np

    segs, _info = t.transcribe(np.zeros(16, dtype=np.float32))
    assert [s.text for s in segs] == ["bonjour", "monde"]  # decode restarted OK
    assert t.device == "cpu"  # self-healed onto CPU
    assert t.model_name == ft.CPU_FILE_MODEL  # no --model → CPU default
    assert "repli sur CPU" in capsys.readouterr().err


def test_decode_wedge_honours_forced_model_on_fallback(monkeypatch, capsys):
    t = _bare_transcriber(
        monkeypatch,
        device="cuda",
        batched=_FakeBatchedWedged(),
        model_override="medium",
    )
    loaded_with = {}

    def fake_load(self, dev, compute, model_name):
        loaded_with["model"] = model_name
        self.device = dev
        self.model_name = model_name
        self._batched = _FakeBatchedOK()

    monkeypatch.setattr(ft.FileTranscriber, "_load", fake_load)

    import numpy as np

    t.transcribe(np.zeros(16, dtype=np.float32))
    assert loaded_with["model"] == "medium"  # explicit --model survives fallback
    assert t.device == "cpu"


def test_decode_failure_on_cpu_reraises_no_retry(monkeypatch):
    t = _bare_transcriber(monkeypatch, device="cpu", batched=_FakeBatchedWedged())

    def fail_load(self, *a, **k):  # must never be called: no fallback from CPU
        raise AssertionError("must not reload when already on CPU")

    monkeypatch.setattr(ft.FileTranscriber, "_load", fail_load)

    import numpy as np

    with pytest.raises(RuntimeError, match="CUDA failed"):
        t.transcribe(np.zeros(16, dtype=np.float32))
