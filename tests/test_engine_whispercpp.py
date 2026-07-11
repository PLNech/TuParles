"""WhisperCppEngine: the promptable CPU rung (#4), tested without the native lib.

The whisper.cpp model is injectable, so the part that's *ours* — prompt
composition, language mapping, the empty-audio guard, partials delegation, and
the GPU→whisper.cpp→qwen fallback chooser — is pinned deterministically with a
fake, no pywhispercpp build required. The real WER-vs-qwen bar (does the prompt
bias actually restore "pipeline" over "payplane") is a real-hardware measurement
(#5b/#19), gated behind the `whispercpp` marker below — never asserted from a
fake.
"""

import numpy as np
import pytest

from tuparles import engine, settings
from tuparles.engine import (
    QwenCpuEngine,
    Transcription,
    WhisperCppEngine,
    _cpu_fallback_factory,
)

AUDIO = np.ones(16_000, dtype=np.int16)  # 1 s of (non-empty) audio


class FakeSeg:
    def __init__(self, text):
        self.text = text


class FakeWhisperModel:
    """Stands in for pywhispercpp's Model: records the last transcribe kwargs so
    we can assert what the engine asked for, and returns canned segments."""

    def __init__(self, segments=(" bonjour ", " world ")):
        self._segments = [FakeSeg(t) for t in segments]
        self.calls = []

    def transcribe(self, pcm, **kwargs):
        self.calls.append(kwargs)
        return self._segments


class FakePartials:
    """A CpuPartialsEngine stand-in carrying a detected language to be borrowed."""

    def __init__(self, lang="en", prob=0.9):
        self.last_language = lang
        self.last_language_prob = prob

    def transcribe_partial(self, audio):
        return "partial"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Hermetic settings dir (same idiom as the GUI tests)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def _engine(model, monkeypatch, *, partials_factory=FakePartials):
    """A WhisperCppEngine wired to a fake model + fake partials, and with the
    vocab glossary stubbed so prompt assertions are hermetic (no vocab files)."""
    monkeypatch.setattr(engine, "_vocab_prompt", lambda: "Glossaire : pipeline")
    return WhisperCppEngine(
        model_factory=lambda name: model, partials_factory=partials_factory
    )


class TestPromptIsTheWholePoint:
    def test_glossary_and_carryover_ride_initial_prompt(self, cfg, monkeypatch):
        # The reason this rung exists: qwen can't take a prompt; whisper.cpp can.
        model = FakeWhisperModel()
        eng = _engine(model, monkeypatch)
        eng.transcribe(AUDIO, context="le take précédent")
        prompt = model.calls[-1]["initial_prompt"]
        assert "Glossaire : pipeline" in prompt
        assert "le take précédent" in prompt
        # carryover rides the TAIL (closest to the decode = strongest bias)
        assert prompt.strip().endswith("le take précédent")

    def test_glossary_alone_when_no_context(self, cfg, monkeypatch):
        model = FakeWhisperModel()
        _engine(model, monkeypatch).transcribe(AUDIO)
        assert model.calls[-1]["initial_prompt"] == "Glossaire : pipeline"


class TestLanguageMapping:
    def test_single_selected_language_pins(self, cfg, monkeypatch):
        settings.put("languages", ["fr"])
        model = FakeWhisperModel()
        _engine(model, monkeypatch).transcribe(AUDIO)
        assert model.calls[-1]["language"] == "fr"

    def test_none_selected_is_auto(self, cfg, monkeypatch):
        settings.put("languages", [])
        model = FakeWhisperModel()
        _engine(model, monkeypatch).transcribe(AUDIO)
        assert model.calls[-1]["language"] == "auto"

    def test_multi_selected_is_auto(self, cfg, monkeypatch):
        # whisper.cpp has no per-segment multilingual flag, so 2+ → detect ("auto")
        settings.put("languages", ["en", "fr"])
        model = FakeWhisperModel()
        _engine(model, monkeypatch).transcribe(AUDIO)
        assert model.calls[-1]["language"] == "auto"


class TestDecodeContract:
    def test_text_joined_and_stripped(self, cfg, monkeypatch):
        model = FakeWhisperModel(segments=[" hello ", " world "])
        out = _engine(model, monkeypatch).transcribe(AUDIO)
        assert out.text == "hello world"

    def test_empty_audio_short_circuits_without_calling_model(self, cfg, monkeypatch):
        model = FakeWhisperModel()
        out = _engine(model, monkeypatch).transcribe(np.zeros(0, dtype=np.int16))
        assert out.text == ""
        assert model.calls == []  # never woke the decoder

    def test_language_borrowed_from_partials_after_a_partial(self, cfg, monkeypatch):
        # qwen-parity (#10): the final decode emits no language of its own; it
        # borrows the small partials model's last detection as the code-switch
        # signal. Built lazily, so it's None until a partial has run.
        settings.put("cpu_partials_enabled", True)
        model = FakeWhisperModel()
        eng = _engine(model, monkeypatch)
        assert eng.transcribe(AUDIO).language is None  # no partial yet
        eng.transcribe_partial(AUDIO)  # builds the (fake) partials model
        out = eng.transcribe(AUDIO)
        assert out.language == "en"
        assert out.language_prob == 0.9


class TestFallbackChooser:
    def test_prefers_whispercpp_when_a_model_loads(self, cfg, monkeypatch):
        monkeypatch.setattr(
            engine, "_default_whispercpp_model", lambda name: FakeWhisperModel()
        )
        assert isinstance(_cpu_fallback_factory(), WhisperCppEngine)

    def test_degrades_to_qwen_when_whispercpp_unavailable(self, cfg, monkeypatch):
        def boom(name):
            raise ImportError("No module named 'pywhispercpp'")

        monkeypatch.setattr(engine, "_default_whispercpp_model", boom)
        assert isinstance(_cpu_fallback_factory(), QwenCpuEngine)


@pytest.mark.whispercpp
def test_real_whispercpp_decodes_silence(cfg):
    """Real native rung (deselected by default; needs `poetry install --with
    whispercpp` + a ggml weight). Proves the pywhispercpp ABI is wired right and a
    decode returns a Transcription without throwing — the smoke test for whoever
    runs the rung on real hardware. The WER-vs-qwen quality bar is #5b/#19; this
    only asserts the plumbing holds."""
    eng = WhisperCppEngine(model="tiny")  # smallest weight; fetched on first use
    out = eng.transcribe(np.zeros(16_000, dtype=np.int16))
    assert isinstance(out, Transcription)
    assert isinstance(out.text, str)
