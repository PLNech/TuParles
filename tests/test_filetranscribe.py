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
    ctranslate2 = pytest.importorskip("ctranslate2")

    _poison_torch(monkeypatch)
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    assert ft.pick_device("auto") == ("cpu", "int8", ft.CPU_FILE_MODEL)


def test_pick_device_auto_uses_ctranslate2_not_torch_cuda(monkeypatch):
    ctranslate2 = pytest.importorskip("ctranslate2")

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


# --- turn seams: silence gaps split fused blocks ------------------
#
# The offline path decodes with word timestamps so a long word-to-word gap
# (a likely speaker hand-off) splits one fused block into visibly separate
# turns, each seamed with "— ". These are model-free: synthetic Segment/Word
# fixtures exercise render_transcript's heuristic directly.


def _render(segments, turn_gap):
    out = ft.render_transcript(
        segments,
        source="x.m4a",
        model="m",
        device="cpu",
        duration=60.0,
        date="2026-07-08",
        turn_gap=turn_gap,
    )
    return [line for line in out.splitlines()[2:] if line]  # body only


def test_word_gap_splits_fused_segment_into_two_turns():
    # A 1.5 s silence (2.0 → 3.5) inside one decoded segment marks a turn change.
    words = (
        ft.Word(0.0, 0.5, " Bonjour"),
        ft.Word(0.5, 1.0, " tout"),
        ft.Word(1.0, 1.5, " le"),
        ft.Word(1.5, 2.0, " monde."),
        ft.Word(3.5, 4.0, " Oui"),
        ft.Word(4.0, 4.5, " salut."),
    )
    seg = ft.Segment(0.0, 4.5, "Bonjour tout le monde. Oui salut.", words)
    body = _render([seg], turn_gap=1.2)
    assert body == ["[00:00] Bonjour tout le monde.", "[00:03] — Oui salut."]


def test_word_gap_below_threshold_does_not_split():
    # Every intra-word gap is <= 1.0 s (an ordinary breath), so no seam appears.
    words = (
        ft.Word(0.0, 0.8, " Bonjour"),
        ft.Word(1.5, 2.3, " tout"),  # 0.7 s gap — under 1.2
        ft.Word(3.0, 3.8, " monde."),  # 0.7 s gap — under 1.2
    )
    seg = ft.Segment(0.0, 3.8, "Bonjour tout monde.", words)
    body = _render([seg], turn_gap=1.2)
    assert body == ["[00:00] Bonjour tout monde."]  # one block, no seam


def test_turn_gap_zero_is_byte_identical_to_legacy():
    # 0 disables the split entirely: output must match the pre-seam renderer even
    # when word gaps AND segment gaps are present.
    words = (
        ft.Word(0.0, 0.5, " un"),
        ft.Word(5.0, 5.5, " deux"),  # huge gap that WOULD split if enabled
    )
    segs = [
        ft.Segment(0.0, 5.5, "un deux", words),
        ft.Segment(30.0, 31.0, "trois", None),  # huge segment gap too
    ]
    body = _render(segs, turn_gap=0)
    assert body == ["[00:00] un deux", "[00:30] trois"]  # no seams, no splits
    assert "—" not in "\n".join(body)


def test_segment_to_segment_gap_gets_seam():
    # No word timings; a 2.0 s gap BETWEEN segments (2.0 → 4.0) still seams.
    segs = [
        ft.Segment(0.0, 2.0, "Première partie."),
        ft.Segment(4.0, 6.0, "Deuxième partie."),
    ]
    body = _render(segs, turn_gap=1.2)
    assert body == ["[00:00] Première partie.", "[00:04] — Deuxième partie."]


def test_words_missing_falls_back_without_crashing():
    # words=None (engine gave no word timings) must never crash: intra-segment
    # splitting is simply skipped, segment-boundary gaps still seam.
    segs = [
        ft.Segment(0.0, 1.0, "alpha", None),
        ft.Segment(1.2, 2.0, "beta", None),  # 0.2 s gap — no seam
        ft.Segment(10.0, 11.0, "gamma", None),  # 8 s gap — seam
    ]
    body = _render(segs, turn_gap=1.2)
    assert body == [
        "[00:00] alpha",
        "[00:01] beta",
        "[00:10] — gamma",
    ]


# --- Segment / Word back-compat (new trailing fields) --------------------
#
# The JSON sidecar added `p` to Word and QC fields to Segment. All are trailing
# + optional so positional construction — and the _FakeSeg decode path, which
# supplies none of them — keeps working, degrading to None (never crash).


def test_segment_positional_construction_defaults_qc_to_none():
    seg = ft.Segment(0.0, 2.0, "bonjour")  # 3 positional args, pre-JSON style
    assert seg.words is None
    assert seg.avg_logprob is None
    assert seg.no_speech_prob is None
    assert seg.compression_ratio is None
    seg2 = ft.Segment(0.0, 2.0, "bonjour", (ft.Word(0.0, 1.0, " bonjour"),))
    assert seg2.words is not None  # 4th positional (words) still lands


def test_word_positional_construction_defaults_p_to_none():
    w = ft.Word(0.0, 0.4, " mot")  # 3 positional args, pre-JSON style
    assert w.p is None
    assert ft.Word(0.0, 0.4, " mot", 0.9).p == 0.9


# --- low_confidence heuristic floors (GH #31 cheap tier) -----------------


def test_low_confidence_floors_each_clause_and_none_safe():
    # Each floor trips independently; every clause is None-safe (an absent metric
    # can't flag a block — we never invent a value to judge).
    assert ft._low_confidence(None, None, None) is False  # all unknown → not flagged
    assert ft._low_confidence(-1.5, 0.0, 5.0) is True  # avg_logprob < -1.0
    assert ft._low_confidence(-0.2, 0.6, 5.0) is True  # no_speech_prob > 0.5
    assert ft._low_confidence(-0.2, 0.0, 0.3) is True  # words_per_s < 0.5
    assert ft._low_confidence(-0.2, 0.0, 5.0) is False  # all healthy
    # A very low avg_logprob with the other two unknown still flags.
    assert ft._low_confidence(-2.0, None, None) is True


# --- render_json: schema golden + QC capture -----------------------------


def _one_seg_with_words():
    """A single fused segment carrying two turns split by a 2.5 s silence, with
    per-word probabilities and per-segment QC — the raw material for the sidecar.
    """
    words = (
        ft.Word(0.0, 0.5, " Bonjour", 0.9),
        ft.Word(0.5, 1.0, " monde.", 0.8),
        ft.Word(3.5, 4.0, " Oui", 0.95),  # 2.5 s gap from prev word → seam
        ft.Word(4.0, 4.5, " salut.", 0.7),
    )
    return ft.Segment(
        0.0,
        4.5,
        "Bonjour monde. Oui salut.",
        words,
        avg_logprob=-0.31,
        no_speech_prob=0.02,
        compression_ratio=1.4,
    )


def test_render_json_schema_golden_with_seam_split():
    seg = _one_seg_with_words()
    data = ft.render_json(
        [seg],
        source="meeting.m4a",
        model="small",
        device="cpu",
        duration=4.53,
        date="2026-07-08",
        language="fr",
        turn_gap=1.2,
    )
    assert data["schema_version"] == 1
    assert data["source"] == "meeting.m4a"
    assert data["duration_s"] == 4.5  # rounded to 1 dp
    assert data["model"] == "small"
    assert data["device"] == "cpu"
    assert data["language"] == "fr"
    assert data["created"] == "2026-07-08"
    assert data["speakers"] is None  # diarization placeholder

    # SAME granularity as the txt: the seam split → two messages.
    assert len(data["messages"]) == 2
    m0, m1 = data["messages"]

    # Block 0: first turn, no seam, clean content (no "— " prefix — txt-only).
    assert m0["start"] == 0.0
    assert m0["end"] == 1.0
    assert m0["content"] == "Bonjour monde."
    a0 = m0["annotations"]
    assert a0["turn_seam"] is False
    assert a0["avg_logprob"] == -0.31  # parent-segment QC, passed through
    assert a0["no_speech_prob"] == 0.02
    assert a0["compression_ratio"] == 1.4
    assert a0["words_per_s"] == 2.0  # 2 words / (1.0 - 0.0) s
    assert a0["low_confidence"] is False
    assert a0["words"] == [
        {"w": "Bonjour", "s": 0.0, "e": 0.5, "p": 0.9},
        {"w": "monde.", "s": 0.5, "e": 1.0, "p": 0.8},
    ]

    # Block 1: second turn, seam opened by the 2.5 s silence.
    assert m1["start"] == 3.5
    assert m1["end"] == 4.5
    assert m1["content"] == "Oui salut."
    a1 = m1["annotations"]
    assert a1["turn_seam"] is True
    # QC repeats the parent segment on the split block (documented behaviour).
    assert a1["avg_logprob"] == -0.31
    assert a1["compression_ratio"] == 1.4
    assert a1["words"][0] == {"w": "Oui", "s": 3.5, "e": 4.0, "p": 0.95}


def test_render_json_matches_txt_block_granularity():
    # The sidecar's message texts must equal the txt body lines (minus the seam
    # glyph + timestamp) — one story, two outputs, via the shared _iter_blocks.
    seg = _one_seg_with_words()
    kw = {
        "source": "x.m4a",
        "model": "m",
        "device": "cpu",
        "duration": 4.5,
        "date": "2026-07-08",
        "turn_gap": 1.2,
    }
    data = ft.render_json([seg], language="fr", **kw)
    body = [ln for ln in ft.render_transcript([seg], **kw).splitlines()[2:] if ln]
    txt_texts = [ln.split("] ", 1)[1].removeprefix(ft.TURN_SEAM) for ln in body]
    json_texts = [m["content"] for m in data["messages"]]
    assert json_texts == txt_texts == ["Bonjour monde.", "Oui salut."]


def test_render_json_sparse_block_flags_low_confidence():
    # A ~30 s block that decoded to 2 words → words_per_s ~0.07 < 0.5 (the real
    # meeting failure the floor was cut for). low_confidence must flag it.
    words = (ft.Word(0.0, 0.4, " euh", 0.3), ft.Word(29.6, 30.0, " voilà", 0.4))
    seg = ft.Segment(
        0.0, 30.0, "euh voilà", words, avg_logprob=-0.5, no_speech_prob=0.1
    )
    # turn_gap=0: keep it as ONE fused block (the real meeting failure was a
    # single sparse block, not a seam-split one) so words_per_s spans the 30 s.
    data = ft.render_json(
        [seg],
        source="x.m4a",
        model="m",
        device="cpu",
        duration=30.0,
        date="d",
        turn_gap=0,
    )
    ann = data["messages"][0]["annotations"]
    assert ann["words_per_s"] is not None and ann["words_per_s"] < 0.5
    assert ann["low_confidence"] is True


def test_render_json_invents_nothing_when_decode_is_silent():
    # No words, no QC (words=None, QC defaulted None): the sidecar must carry
    # None, never a fabricated number. words_per_s is None (no word count).
    seg = ft.Segment(0.0, 2.0, "bonjour")  # bare positional, pre-JSON style
    data = ft.render_json(
        [seg], source="x.m4a", model="m", device="cpu", duration=2.0, date="d"
    )
    (m,) = data["messages"]
    a = m["annotations"]
    assert data["language"] is None  # not passed → None, not guessed
    assert a["avg_logprob"] is None
    assert a["no_speech_prob"] is None
    assert a["compression_ratio"] is None
    assert a["words_per_s"] is None
    assert a["words"] is None
    assert a["low_confidence"] is False  # nothing known → nothing flagged


# --- cli sidecar wiring: default on, --no-json, non-clobber ---------------


def _run_transcribe(tmp_path, monkeypatch, **overrides):
    """Drive cli._transcribe model-free: a fake transcriber yields one synthetic
    segment, decode_to_pcm is stubbed, settings answer in-memory. Returns the
    input path so a test can assert on its sibling sidecars."""
    import argparse

    import numpy as np

    from tuparles import cli

    src = tmp_path / "talk.m4a"
    src.write_bytes(b"not-real-audio")

    class _Info:
        language = "fr"

    class _FakeTranscriber:
        def __init__(self, device="auto", model=None):
            self.model_name = "small"
            self.device = "cpu"

        def transcribe(self, pcm, progress=None):
            seg = ft.Segment(
                0.0, 1.0, "bonjour", None, avg_logprob=-0.2, no_speech_prob=0.01
            )
            return [seg], _Info()

    monkeypatch.setattr(ft, "FileTranscriber", _FakeTranscriber)
    monkeypatch.setattr(
        ft, "decode_to_pcm", lambda p: np.zeros(16000, dtype=np.float32)
    )
    fake = {"transcribe_json": True, "turn_gap_s": 1.2, "languages": []}
    fake.update(overrides.pop("settings", {}))
    monkeypatch.setattr(ft.settings, "get", lambda key, *a: fake.get(key))

    args = argparse.Namespace(
        files=[str(src)],
        force=False,
        device="auto",
        model=None,
        turn_gap=None,
        no_json=False,
        stdout=False,
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    cli._transcribe(args)
    return src


def test_cli_writes_both_txt_and_json_by_default(tmp_path, monkeypatch):
    src = _run_transcribe(tmp_path, monkeypatch)
    txt = src.with_name("talk-transcript.txt")
    js = src.with_name("talk-transcript.json")
    assert txt.exists() and js.exists()
    import json

    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["language"] == "fr"  # info.language flows through
    assert data["messages"][0]["content"] == "bonjour"


def test_cli_no_json_flag_skips_sidecar(tmp_path, monkeypatch):
    src = _run_transcribe(tmp_path, monkeypatch, no_json=True)
    assert src.with_name("talk-transcript.txt").exists()
    assert not src.with_name("talk-transcript.json").exists()


def test_cli_transcribe_json_setting_off_skips_sidecar(tmp_path, monkeypatch):
    src = _run_transcribe(tmp_path, monkeypatch, settings={"transcribe_json": False})
    assert src.with_name("talk-transcript.txt").exists()
    assert not src.with_name("talk-transcript.json").exists()


def test_cli_non_clobber_preserves_existing_json(tmp_path, monkeypatch):
    # A pre-existing sidecar we didn't just make must survive a run without
    # --force (implicit destruction is still destruction); the txt still writes.
    src = tmp_path / "talk.m4a"
    js = tmp_path / "talk-transcript.json"
    js.write_text('{"schema_version": 1, "mine": true}\n', encoding="utf-8")
    _run_transcribe(tmp_path, monkeypatch)  # writes src, decodes, honours skip
    import json

    assert json.loads(js.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "mine": True,
    }  # untouched
    assert src.with_name("talk-transcript.txt").exists()  # txt still produced


def test_cli_force_overwrites_existing_json(tmp_path, monkeypatch):
    js = tmp_path / "talk-transcript.json"
    js.write_text('{"mine": true}\n', encoding="utf-8")
    _run_transcribe(tmp_path, monkeypatch, force=True)
    import json

    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1  # regenerated, not the stub
    assert "mine" not in data
