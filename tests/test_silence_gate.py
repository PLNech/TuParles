"""#54: `tuparles transcribe` on near-silence — two structural layers.

(a) the pre-decode silence gate (`preprocess.silence_gate`): a file is skipped
    only when a speech detector found NO speech AND the energy has no structure
    (fewer than 160 ms of frames 6 dB over the floor). Either clause alone means
    "decode": a gated real utterance is a black hole, a hallucination is visible.
(b) the post-decode loop guard (`repeats.find_loop` / `cut_loops`, applied to
    segments by `filetranscribe.guard_repetition`): a phrase repeated verbatim
    4+ times over 12+ words keeps ONE copy and is flagged.

Every signal here is seeded synthetic audio; no model, no real recording.
"""

import json

import numpy as np
import pytest

import tuparles.filetranscribe as ft
import tuparles.preprocess as pp
from tuparles.repeats import cut_loops, find_loop

SR = 16000


# --- seeded synthetic signals ------------------------------------------------


def _db(x: np.ndarray, db: float) -> np.ndarray:
    return x * (10.0 ** (db / 20.0))


def _hiss(seconds: float, db: float = -50.0, seed: int = 54) -> np.ndarray:
    """Pink-ish hiss (1/f power, high-passed at 20 Hz like any real mic chain),
    scaled to `db` dBFS RMS."""
    n = int(seconds * SR)
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    g = np.zeros_like(f)
    g[f >= 20] = 1.0 / np.sqrt(f[f >= 20])
    x = np.fft.irfft(spec * g, n)
    return _db(x / np.sqrt(np.mean(x**2)), db)


def _with_clicks(x: np.ndarray, times, peak_db: float = -30.0) -> np.ndarray:
    """5 ms decaying clicks (a keyboard tick, a cable knock) peaking at `peak_db`."""
    x = x.copy()
    k = np.arange(80)
    click = 10 ** (peak_db / 20) * np.exp(-k / 12.0) * np.sign(np.sin(k * 1.7))
    for t in times:
        i = int(t * SR)
        x[i : i + 80] += click
    return x


def _hum(seconds: float) -> np.ndarray:
    """Mains hum (50 + 100 Hz) at -45 dBFS RMS over -55 dBFS hiss."""
    t = np.arange(int(seconds * SR)) / SR
    hum = np.sin(2 * np.pi * 50 * t) + 0.4 * np.sin(2 * np.pi * 100 * t)
    return _db(hum / np.sqrt(np.mean(hum**2)), -45.0) + _hiss(seconds, -55.0, seed=2)


def _lowband(seconds: float, db: float = -60.0) -> np.ndarray:
    """Very low-level noise band-limited to the speech band (300-3400 Hz)."""
    n = int(seconds * SR)
    spec = np.fft.rfft(np.random.default_rng(3).standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec[(f < 300) | (f > 3400)] = 0
    x = np.fft.irfft(spec, n)
    return _db(x / np.sqrt(np.mean(x**2)), db)


def _syllables(
    total: float, start: float, dur: float, level_db: float, seed: int = 7
) -> np.ndarray:
    """Speech-like energy: 120-220 ms harmonic bursts (f0 110-220 Hz under two
    formants) separated by 40-120 ms gaps, from `start` for `dur` seconds, at
    `level_db` dBFS RMS over the active span. Not speech — but it has speech's
    energy structure, which is all the gate is allowed to look at."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(total * SR))
    t, end = start, start + dur
    while t < end:
        length = rng.uniform(0.12, 0.22)
        tt = np.arange(int(length * SR)) / SR
        f0 = rng.uniform(110, 220)
        v = sum(
            (
                np.exp(-(((f0 * h - 600) / 300) ** 2))
                + 0.5 * np.exp(-(((f0 * h - 1500) / 400) ** 2))
            )
            * np.sin(2 * np.pi * f0 * h * tt)
            for h in range(1, 25)
        )
        v = v * np.hanning(v.size)
        i = int(t * SR)
        seg = out[i : i + v.size]
        seg += v[: seg.size]
        t += length + rng.uniform(0.04, 0.12)
    active = out[int(start * SR) : int(end * SR)]
    return out * (10 ** (level_db / 20) / max(np.sqrt(np.mean(active**2)), 1e-12))


def _f32(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float32)


# A speech detector that ran and found nothing / found speech / is missing.
NO_SPEECH = [("fake-vad", lambda audio, sr: None)]
SPEECH = [("fake-vad", lambda audio, sr: (0, audio.size))]


def _missing(audio, sr):
    raise ImportError("no detector here")


# --- (a) the gate decision -----------------------------------------------------


class TestGateGatesNoSpeech:
    """Detector says no speech AND no energy structure → gated."""

    @pytest.mark.parametrize(
        "signal",
        [
            pytest.param(lambda: _hiss(30.0), id="hiss"),
            pytest.param(
                lambda: _with_clicks(_hiss(30.0), (3.2, 11.7, 19.4, 26.1)),
                id="hiss+clicks",
            ),
            pytest.param(
                lambda: _with_clicks(_hiss(30.0), np.linspace(0.5, 29.0, 40)),
                id="hiss+40clicks",
            ),
            pytest.param(lambda: _hum(30.0), id="hum"),
            pytest.param(lambda: _lowband(30.0), id="lowband"),
            pytest.param(lambda: np.zeros(30 * SR), id="digital-zero"),
        ],
    )
    def test_gated(self, signal):
        v = pp.silence_gate(_f32(signal()), SR, detectors=NO_SPEECH)
        assert v.gated is True
        assert v.reason == "no_speech"
        assert v.detector == "fake-vad"
        assert v.active_s < 0.16

    def test_int16_input_is_judged_like_float(self):
        x = _with_clicks(_hiss(30.0), (3.2, 11.7))
        i16 = np.clip(np.rint(x * 32767), -32768, 32767).astype(np.int16)
        assert pp.silence_gate(i16, SR, detectors=NO_SPEECH).gated is True

    def test_verdict_records_levels_for_forensics(self):
        v = pp.silence_gate(_f32(_hiss(30.0)), SR, detectors=NO_SPEECH)
        d = v.as_dict()
        assert d["gated"] is True and d["reason"] == "no_speech"
        assert -54.0 < d["floor_dbfs"] < -48.0  # the -50 dBFS hiss floor
        assert d["level_dbfs"] >= d["floor_dbfs"]
        assert d["peak_dbfs"] is not None
        json.dumps(d)  # native types only — it lands in the sidecar


class TestGateNeverEatsSpeech:
    """Energy structure alone vetoes the gate, even if the detector missed it."""

    def test_quiet_speech_like_bursts_over_a_floor(self):
        x = _hiss(30.0) + _syllables(30.0, 5.0, 10.0, -42.0)
        v = pp.silence_gate(_f32(x), SR, detectors=NO_SPEECH)
        assert v.gated is False
        assert v.reason == "energy_structure"

    def test_faint_three_second_phrase(self):
        x = _hiss(30.0) + _syllables(30.0, 12.0, 3.0, -44.0)
        assert pp.silence_gate(_f32(x), SR, detectors=NO_SPEECH).gated is False

    @pytest.mark.parametrize("level", [-40.0, -44.0])
    def test_single_short_word_burst(self, level):
        # One 0.6 s word in 30 s of hiss: 2% of frames, so a percentile can't
        # see it — the gate must still decode.
        x = _hiss(30.0) + _syllables(30.0, 14.0, 0.6, level, seed=9)
        v = pp.silence_gate(_f32(x), SR, detectors=NO_SPEECH)
        assert v.gated is False
        assert v.active_s >= 0.16

    def test_near_field_speech(self):
        x = _hiss(30.0) + _syllables(30.0, 2.0, 25.0, -20.0)
        assert pp.silence_gate(_f32(x), SR, detectors=NO_SPEECH).gated is False

    def test_detector_finding_speech_vetoes_a_flat_file(self):
        v = pp.silence_gate(_f32(_hiss(30.0)), SR, detectors=SPEECH)
        assert v.gated is False
        assert v.reason == "speech_detected"

    def test_no_working_detector_means_decode(self):
        v = pp.silence_gate(_f32(_hiss(30.0)), SR, detectors=[("gone", _missing)])
        assert v.gated is False
        assert v.reason == "no_detector"

    def test_falls_through_a_missing_detector_to_the_next(self):
        v = pp.silence_gate(
            _f32(_hiss(30.0)), SR, detectors=[("gone", _missing), *NO_SPEECH]
        )
        assert v.gated is True and v.detector == "fake-vad"

    def test_too_short_to_judge_is_decoded(self):
        v = pp.silence_gate(
            np.zeros(SR // 4, dtype=np.float32), SR, detectors=NO_SPEECH
        )
        assert v.gated is False
        assert v.reason == "too_short"

    def test_never_raises_on_garbage(self):
        v = pp.silence_gate(
            np.full(SR * 2, np.nan, dtype=np.float32), SR, detectors=NO_SPEECH
        )
        assert v.gated is False

    def test_rms_tier_is_conservative_on_clicks(self, monkeypatch):
        # Without a real VAD the default tiers fall to the RMS span, which is
        # relative to the loudest frame: one click makes it report "speech",
        # so hiss+clicks is decoded, not gated. Conservative by construction.
        monkeypatch.setattr(pp, "_silero_speech_span", _missing)
        x = _with_clicks(_hiss(30.0), (3.2, 11.7, 19.4, 26.1))
        v = pp.silence_gate(_f32(x), SR)
        assert v.gated is False and v.detector == "rms"

    def test_rms_tier_gates_digital_silence(self, monkeypatch):
        monkeypatch.setattr(pp, "_silero_speech_span", _missing)
        v = pp.silence_gate(np.zeros(30 * SR, dtype=np.float32), SR)
        assert v.gated is True and v.detector == "rms"


# --- (b) the loop guard, on tokens -------------------------------------------


class TestFindLoop:
    def test_looped_phrase_is_found_at_its_start(self):
        toks = "bonjour à tous".split() + "merci d'avoir regardé".split() * 30
        assert find_loop(toks) == (3, 3, 30)

    def test_minimal_period_wins(self):
        assert find_loop(["la"] * 40) == (0, 1, 40)

    def test_punctuation_and_case_do_not_hide_a_loop(self):
        toks = ["Thank", "you."] * 5 + ["thank", "YOU!"] * 5
        assert find_loop(toks) == (0, 2, 10)

    @pytest.mark.parametrize(
        "text",
        [
            "non non non c'est pas ça",  # an honest triple
            "très très très très bien",  # 4 copies but 4 words
            "on y va on y va on y va",  # a chant, 3 copies
            "je pense que je pense que c'est bon",
            "Thank you. Thank you. Thank you. Thank you.",  # 4 copies, 8 words
            "",
        ],
    )
    def test_honest_repetition_is_not_a_loop(self, text):
        assert find_loop(text.split()) is None

    @pytest.mark.parametrize("words", [1, 2, 3, 5])
    @pytest.mark.parametrize("copies", [8, 12, 40])
    def test_long_loops_are_found(self, words, copies):
        phrase = ["w0", "w1", "w2", "w3", "w4"][:words]
        hit = find_loop(["intro"] + phrase * copies)
        if words * copies >= 16:
            assert hit == (1, words, copies)
        else:  # "zero" x8 / x12: enough copies, too few words — left alone
            assert hit is None


# The blind verifier's legitimate repeats (all <= 6 copies). Every one of them
# was cut by the first 4-copy rule; under 8 copies + 16 words none may be.
LEGIT_REPEATS = {
    "ship-x4": "We need to ship this now. " * 4,
    "fr-x4": "c'est pas possible " * 4,
    "let-it-be-x4": "let it be " * 4,
    "and-then-x4": "and then we went " * 4,
    "pin-x6": "the code is " + "one two " * 6,
    "thanks-x6": "Thank you. " * 6,
    "zero-x12": "zero " * 12,
    "return-none-x6": "return none " * 6,
    "code-x4": "self dot x equals " * 4,
}


@pytest.mark.parametrize("name", sorted(LEGIT_REPEATS))
def test_legitimate_repeats_come_back_unchanged(name):
    text = LEGIT_REPEATS[name].strip()
    assert find_loop(text.split()) is None
    seg = ft.Segment(0.0, 5.0, text)
    assert ft.guard_repetition([seg]) == [seg]
    words = text.split()
    wseg = ft.Segment(0.0, 5.0, text, _w(words))
    assert ft.guard_repetition([wseg]) == [wseg]


class TestCutLoops:
    def test_keeps_one_copy_and_drops_the_partial_tail(self):
        toks = "bonjour".split() + "merci d'avoir regardé".split() * 8 + ["merci"]
        kept, loops = cut_loops(toks)
        assert kept == list(range(4))  # bonjour + one copy
        assert loops == [(1, 3, 8)]

    def test_text_after_the_loop_survives(self):
        toks = ["a", "b"] + ["x", "y", "z"] * 8 + ["real", "words"]
        kept, loops = cut_loops(toks)
        assert [toks[i] for i in kept] == ["a", "b", "x", "y", "z", "real", "words"]
        assert loops == [(2, 3, 8)]

    def test_untouched_when_no_loop(self):
        toks = "on y va on y va on y va".split()
        kept, loops = cut_loops(toks)
        assert kept == list(range(len(toks))) and loops == []

    def test_empty_is_safe(self):
        assert cut_loops([]) == ([], [])


# --- (b) the loop guard, on segments -----------------------------------------


def _w(words, t0=0.0, step=0.3):
    return tuple(
        ft.Word(t0 + i * step, t0 + (i + 1) * step, f" {w}", 0.9)
        for i, w in enumerate(words)
    )


class TestGuardRepetition:
    def test_looped_segment_is_cut_and_flagged(self):
        words = ["Bonjour."] + ["Merci", "d'avoir", "regardé."] * 20
        seg = ft.Segment(0.0, 18.3, " ".join(words), _w(words))
        (out,) = ft.guard_repetition([seg])
        assert out.text == "Bonjour. Merci d'avoir regardé."
        assert len(out.words) == 4
        assert out.end == pytest.approx(1.2)  # the span shrinks to what's kept
        assert out.repetition == ("Merci d'avoir regardé.", 20)

    def test_segment_without_words_is_cut_on_text(self):
        seg = ft.Segment(0.0, 30.0, "the " * 40)
        (out,) = ft.guard_repetition([seg])
        assert out.text == "the"
        assert out.repetition == ("the", 40)
        assert out.end == 30.0  # no word timings: the span is left as decoded

    def test_loop_across_segments_keeps_the_first(self):
        segs = [ft.Segment(i * 2.0, i * 2.0 + 2.0, "Thank you.") for i in range(10)]
        out = ft.guard_repetition(segs)
        assert [s.text for s in out] == ["Thank you."]
        assert out[0].repetition == ("Thank you.", 10)

    def test_normal_text_is_returned_unchanged(self):
        segs = [
            ft.Segment(0.0, 2.0, "non non non c'est pas ça"),
            ft.Segment(2.0, 4.0, "Oui."),
            ft.Segment(4.0, 6.0, "Oui."),
            ft.Segment(6.0, 8.0, "Oui."),
            ft.Segment(8.0, 9.0, "Oui."),
        ]
        out = ft.guard_repetition(segs)
        assert out == segs
        assert all(s.repetition is None for s in out)

    def test_empty_is_safe(self):
        assert ft.guard_repetition([]) == []
        blank = [ft.Segment(0.0, 1.0, "")]
        assert ft.guard_repetition(blank) == blank


def test_cut_segment_is_marked_in_txt_and_annotated_in_json():
    seg = ft.Segment(0.0, 30.0, "the " * 40)
    (cut,) = ft.guard_repetition([seg])
    kw = {"source": "x.wav", "model": "m", "device": "cpu", "duration": 30.0}
    txt = ft.render_transcript([cut], date="d", turn_gap=0, **kw)
    assert txt.splitlines()[2] == "[00:00] the […×40]"
    data = ft.render_json([cut], date="d", turn_gap=0, **kw)
    assert data["truncated_repetition"] is True
    (m,) = data["messages"]
    assert m["content"] == "the"  # content stays clean, the mark is txt-only
    assert m["annotations"]["repetition"] == {"phrase": "the", "copies": 40}


_KW = {"source": "x.wav", "model": "m", "device": "cpu", "duration": 30.0}


def _body(segments, turn_gap=0):
    txt = ft.render_transcript(segments, date="d", turn_gap=turn_gap, **_KW)
    return txt.splitlines()[2:]


def test_marker_sits_at_the_cut_mid_text_without_words():
    # loop_midtext: real text, a loop, real text again — the marker goes
    # between the surviving copy and the tail, with the count.
    text = "So we started. " + "and then we went " * 12 + "to the beach."
    (cut,) = ft.guard_repetition([ft.Segment(0.0, 30.0, text)])
    assert _body([cut]) == [
        "[00:00] So we started. and then we went […×12] to the beach."
    ]


def test_marker_sits_at_the_cut_mid_text_with_words():
    words = ["Bonjour."] + ["Merci", "d'avoir", "regardé."] * 20 + ["Au", "revoir."]
    seg = ft.Segment(0.0, 18.9, " ".join(words), _w(words))
    (cut,) = ft.guard_repetition([seg])
    assert cut.text == "Bonjour. Merci d'avoir regardé. Au revoir."
    assert _body([cut]) == ["[00:00] Bonjour. Merci d'avoir regardé. […×20] Au revoir."]


def test_marker_follows_the_surviving_turn_seam_block():
    # The cut lands in the first of two turn-split blocks: the mark stays at
    # the cut, the second block is untouched.
    words = ["Bonjour."] + ["la", "di"] * 10
    timed = (*_w(words), ft.Word(20.0, 20.5, " Salut.", 0.9))
    seg = ft.Segment(0.0, 20.5, " ".join(words) + " Salut.", timed)
    (cut,) = ft.guard_repetition([seg])
    assert _body([cut], turn_gap=1.2) == [
        "[00:00] Bonjour. la di […×10]",
        "[00:20] — Salut.",
    ]


def test_marker_follows_the_surviving_segment_of_a_split_loop():
    segs = [ft.Segment(i * 2.0, i * 2.0 + 2.0, "Thank you.") for i in range(12)]
    segs.append(ft.Segment(24.0, 26.0, "Bye."))
    out = ft.guard_repetition(segs)
    assert _body(out) == ["[00:00] Thank you. […×12]", "[00:24] Bye."]


def test_split_emphasis_once_per_segment_is_untouched():
    segs = [ft.Segment(i * 2.0, i * 2.0 + 2.0, "we ship it now") for i in range(4)]
    assert ft.guard_repetition(segs) == segs
    assert not any("[…" in ln for ln in _body(segs))


def test_render_json_defaults_for_new_keys():
    data = ft.render_json(
        [ft.Segment(0.0, 1.0, "bonjour")],
        source="x",
        model="m",
        device="cpu",
        duration=1.0,
        date="d",
    )
    assert data["truncated_repetition"] is False
    assert data["no_speech"] is None
    assert data["language_probability"] is None
    assert data["messages"][0]["annotations"]["repetition"] is None


# --- the decode seam ----------------------------------------------------------


def test_decode_does_not_let_faster_whisper_mutate_the_shared_vad_params(
    monkeypatch,
):
    # BatchedInferencePipeline.transcribe pops "max_speech_duration_s" from the
    # dict it is handed. Handing it the module-level TUNED_VAD_PARAMETERS would
    # strip that key for every later caller in the process.
    from tuparles.engine import TUNED_VAD_PARAMETERS

    before = dict(TUNED_VAD_PARAMETERS)

    class _Popping:
        def transcribe(self, pcm, **kw):
            kw["vad_parameters"].pop("max_speech_duration_s", None)
            return iter([]), object()

    monkeypatch.setattr(ft.settings, "get", lambda *a, **k: [])
    monkeypatch.setattr(ft, "_vocab_prompt", lambda: None)
    t = ft.FileTranscriber.__new__(ft.FileTranscriber)
    t.device, t.model_name, t._model_override = "cpu", "small", None
    t._batched = _Popping()
    t.transcribe(np.zeros(16, dtype=np.float32))
    assert before == TUNED_VAD_PARAMETERS


def test_decoder_vad_tier_agrees_with_the_decoder_on_silence():
    pytest.importorskip("faster_whisper")
    from tuparles.engine import TUNED_VAD_PARAMETERS

    before = dict(TUNED_VAD_PARAMETERS)
    assert ft._decoder_vad_span(np.zeros(5 * SR, dtype=np.float32), SR) is None
    assert before == TUNED_VAD_PARAMETERS


# --- CLI wiring: gated files never reach the model ----------------------------


class _Calls:
    def __init__(self):
        self.constructed = 0
        self.decoded = 0


def _cli(tmp_path, monkeypatch, *, pcm, segments=None, settings=None, **flags):
    import argparse

    from tuparles import cli

    src = tmp_path / "quiet.wav"
    src.write_bytes(b"not-real-audio")
    calls = _Calls()

    class _Info:
        language = "fr"
        language_probability = 0.91

    class _FakeTranscriber:
        def __init__(self, device="auto", model=None):
            calls.constructed += 1
            self.model_name = "small"
            self.device = "cpu"

        def transcribe(self, pcm, progress=None):
            calls.decoded += 1
            if segments is not None:
                return list(segments), _Info()
            return [ft.Segment(0.0, 1.0, "bonjour")], _Info()

    monkeypatch.setattr(ft, "FileTranscriber", _FakeTranscriber)
    monkeypatch.setattr(ft, "decode_to_pcm", lambda p: pcm)
    # Hermetic detector: "the decoder's VAD found nothing" (CI has no
    # faster-whisper; locally it would answer for real).
    monkeypatch.setattr(ft, "_decoder_vad_span", lambda audio, sr: None)
    fake = {
        "transcribe_json": True,
        "turn_gap_s": 1.2,
        "languages": [],
        "silence_gate": True,
        "repetition_guard": True,
    }
    fake.update(settings or {})
    monkeypatch.setattr(ft.settings, "get", lambda key, *a: fake.get(key))
    args = argparse.Namespace(
        files=[str(src)],
        force=False,
        device="cpu",
        model=None,
        turn_gap=None,
        no_json=False,
        stdout=False,
        no_silence_gate=False,
        no_repetition_guard=False,
    )
    for k, v in flags.items():
        setattr(args, k, v)
    cli._transcribe(args)
    txt = src.with_name("quiet-transcript.txt")
    js = src.with_name("quiet-transcript.json")
    data = json.loads(js.read_text(encoding="utf-8")) if js.exists() else None
    return calls, txt, data


def _quiet_file():
    return _f32(_with_clicks(_hiss(30.0), (3.2, 11.7, 19.4, 26.1)))


def test_cli_gated_file_skips_the_model_entirely(tmp_path, monkeypatch, capsys):
    calls, txt, data = _cli(tmp_path, monkeypatch, pcm=_quiet_file())
    assert calls.constructed == 0 and calls.decoded == 0  # no load, no decode
    out = capsys.readouterr()
    assert "Aucune parole détectée" in out.out
    assert "porte de silence" in out.err  # the decision + levels, on stderr
    assert "aucune parole détectée" in txt.read_text(encoding="utf-8")
    assert data["messages"] == []
    assert data["language"] is None  # no detection ran, none is reported
    assert data["model"] is None and data["device"] is None
    ns = data["no_speech"]
    assert ns["reason"] == "silence_gate"
    assert ns["gated"] is True and ns["detector"] == "faster-whisper-vad"
    assert ns["floor_dbfs"] is not None


def test_cli_no_silence_gate_flag_decodes(tmp_path, monkeypatch):
    calls, _txt, data = _cli(
        tmp_path, monkeypatch, pcm=_quiet_file(), no_silence_gate=True
    )
    assert calls.decoded == 1
    assert data["messages"][0]["content"] == "bonjour"
    assert data["no_speech"] is None
    assert data["language_probability"] == 0.91


def test_cli_silence_gate_setting_off_decodes(tmp_path, monkeypatch):
    calls, _txt, _data = _cli(
        tmp_path, monkeypatch, pcm=_quiet_file(), settings={"silence_gate": False}
    )
    assert calls.decoded == 1


def test_cli_speech_is_decoded_with_the_gate_on(tmp_path, monkeypatch):
    pcm = _f32(_hiss(30.0) + _syllables(30.0, 2.0, 25.0, -20.0))
    calls, _txt, data = _cli(tmp_path, monkeypatch, pcm=pcm)
    assert calls.decoded == 1
    assert data["no_speech"] is None


def test_cli_decoder_returning_nothing_says_so(tmp_path, monkeypatch, capsys):
    calls, txt, data = _cli(
        tmp_path, monkeypatch, pcm=_quiet_file(), segments=[], no_silence_gate=True
    )
    assert calls.decoded == 1
    assert "Aucune parole détectée" in capsys.readouterr().out
    assert data["no_speech"] == {"reason": "decoder_empty"}
    assert "aucune parole détectée" in txt.read_text(encoding="utf-8")


def test_cli_loop_is_cut_and_reported(tmp_path, monkeypatch, capsys):
    looped = [ft.Segment(0.0, 30.0, "Merci d'avoir regardé. " * 25)]
    calls, txt, data = _cli(
        tmp_path, monkeypatch, pcm=_quiet_file(), segments=looped, no_silence_gate=True
    )
    out = capsys.readouterr()
    assert "boucle" in out.out
    assert data["truncated_repetition"] is True
    assert data["messages"][0]["content"] == "Merci d'avoir regardé."
    assert txt.read_text(encoding="utf-8").count("Merci") == 1


def test_cli_repetition_guard_setting_off_keeps_the_raw_decode(tmp_path, monkeypatch):
    looped = [ft.Segment(0.0, 30.0, "Merci d'avoir regardé. " * 25)]
    _calls, _txt, data = _cli(
        tmp_path,
        monkeypatch,
        pcm=_quiet_file(),
        segments=looped,
        no_silence_gate=True,
        settings={"repetition_guard": False},
    )
    assert data["truncated_repetition"] is False
    assert data["messages"][0]["content"].count("Merci") == 25


# --- settings ------------------------------------------------------------------


def test_silence_gate_and_repetition_guard_default_on():
    from tuparles import settings

    assert settings._DEFAULTS["silence_gate"] is True
    assert settings._DEFAULTS["repetition_guard"] is True
    assert settings.get("silence_gate") is True  # isolated, nothing stored


def test_cli_no_repetition_guard_flag_keeps_the_raw_decode(tmp_path, monkeypatch):
    looped = [ft.Segment(0.0, 30.0, "Merci d'avoir regardé. " * 25)]
    _calls, txt, data = _cli(
        tmp_path,
        monkeypatch,
        pcm=_quiet_file(),
        segments=looped,
        no_silence_gate=True,
        no_repetition_guard=True,
    )
    assert data["truncated_repetition"] is False
    assert data["messages"][0]["content"].count("Merci") == 25
    assert "[…" not in txt.read_text(encoding="utf-8")


def test_cli_names_the_cut_on_stderr_and_marks_it_in_txt(tmp_path, monkeypatch, capsys):
    looped = [
        ft.Segment(
            0.0, 30.0, "Bonjour. " + "Merci d'avoir regardé. " * 25 + "Au revoir."
        )
    ]
    _calls, txt, data = _cli(
        tmp_path, monkeypatch, pcm=_quiet_file(), segments=looped, no_silence_gate=True
    )
    err = capsys.readouterr().err
    assert "« Merci d'avoir regardé. » ×25" in err
    body = txt.read_text(encoding="utf-8").splitlines()[2:]
    assert body == ["[00:00] Bonjour. Merci d'avoir regardé. […×25] Au revoir."]
    assert data["messages"][0]["annotations"]["repetition"] == {
        "phrase": "Merci d'avoir regardé.",
        "copies": 25,
    }
