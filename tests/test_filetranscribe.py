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
