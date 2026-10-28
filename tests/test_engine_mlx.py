"""MlxEngine and the Apple Silicon chooser, with the library faked.

The real Metal decode is a bench, not a unit test: it needs the weights and
the GPU. Here the contract is what the daemon sees — a Transcription, a
partial string, and load_engine picking MLX on a Mac that has the package.
"""

import sys
import types

import numpy as np
import pytest

from tuparles import engine
from tuparles.engine import MlxEngine, _words_from_mlx
from tuparles.transcription import Transcription


class _FakeMlx:
    """Stands in for mlx_whisper. Records the kwargs of the last transcribe."""

    def __init__(self, text="bonjour fan out", language="fr"):
        self.calls = []
        self._text = text
        self._language = language
        self.transcribe = self._transcribe
        self.audio = types.SimpleNamespace(
            N_SAMPLES=480000,
            N_FRAMES=3000,
            log_mel_spectrogram=lambda *a, **k: None,
            pad_or_trim=lambda *a, **k: None,
        )

    def _transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return {
            "text": self._text,
            "language": self._language,
            "segments": [
                {
                    "text": self._text,
                    "words": [
                        {"word": "bonjour", "start": 0.0, "end": 0.4},
                        {"word": "fan out", "start": 0.5, "end": 0.9, "probability": 0.4},
                    ],
                }
            ],
        }


def _engine(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    monkeypatch.setattr(engine.settings, "get", lambda key: None)
    return MlxEngine(model="mlx-community/whisper-large-v3-turbo")


def test_final_returns_transcription(monkeypatch):
    fake = _FakeMlx()
    eng = _engine(monkeypatch, fake)
    # The constructor warms the model with one silent call.
    out = eng.transcribe(np.zeros(16_000, dtype=np.int16), context="prise précédente")
    assert isinstance(out, Transcription)
    assert out.text == "bonjour fan out"
    assert out.language == "fr"
    assert out.words[0].probability == 1.0  # no score → no dimming
    assert out.words[1].probability == pytest.approx(0.4)
    last = fake.calls[-1]
    assert eng.last_segments  # the file path reads these back
    assert last["word_timestamps"] is True
    assert last["temperature"] == 0.0
    assert "prise précédente" in last["initial_prompt"]


def test_partial_skips_word_timestamps(monkeypatch):
    fake = _FakeMlx(text="en cours")
    eng = _engine(monkeypatch, fake)
    assert eng.transcribe_partial(np.zeros(16_000, dtype=np.int16)) == "en cours"
    assert fake.calls[-1]["word_timestamps"] is False
    assert fake.calls[-1]["initial_prompt"] is None


def test_empty_audio_skips_the_model(monkeypatch):
    fake = _FakeMlx()
    eng = _engine(monkeypatch, fake)
    before = len(fake.calls)
    assert eng.transcribe(np.zeros(0, dtype=np.int16)) == Transcription("")
    assert eng.transcribe_partial(np.zeros(0, dtype=np.int16)) == ""
    assert len(fake.calls) == before


def test_words_without_text_are_dropped():
    words = _words_from_mlx([{"words": [{"word": ""}, {"word": "ok", "start": 1.0}]}])
    assert [w.text for w in words] == ["ok"]


def test_load_engine_picks_mlx_on_mac(monkeypatch):
    fake = _FakeMlx()
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    monkeypatch.setattr(engine, "IS_MACOS", True)
    monkeypatch.setattr(engine.settings, "get", lambda key: False)
    built = []
    monkeypatch.setattr(engine, "MlxEngine", lambda: built.append("mlx") or fake)
    assert engine.load_engine() is fake
    assert built == ["mlx"]


def test_load_engine_skips_mlx_off_mac(monkeypatch):
    monkeypatch.setattr(engine, "IS_MACOS", False)
    monkeypatch.setattr(engine, "apple_gpu_available", lambda: False)
    monkeypatch.setattr(engine, "ResilientEngine", lambda: "cuda")
    assert engine.load_engine() == "cuda"


def test_mlx_load_failure_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(engine, "apple_gpu_available", lambda: True)
    monkeypatch.setattr(engine.settings, "get", lambda key: False)

    def boom():
        raise RuntimeError("metal wedged")

    monkeypatch.setattr(engine, "MlxEngine", boom)
    monkeypatch.setattr(engine, "_cpu_fallback_factory", lambda: "cpu")
    assert engine.load_engine() == "cpu"
