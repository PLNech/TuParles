"""Integration: run Whisper on the synthesised code-switch WAVs.

This is the suite the whole exercise is for. It is gated three ways and will
*skip* (never error) when any gate is shut:
  * marked `gpu` — deselected unless you opt in (`pytest -m gpu`)
  * skips if there is no CUDA device (CI, or a wedged context)
  * skips if no WAVs were generated yet (run scripts/gen_codeswitch_wavs.py)

It exercises the FULL user-facing path — engine decode → `pipeline.postprocess`
(punctuation + lexicon + repeat-collapse) — so a pass means "what the user
would have seen survives", not "the raw model logits were fine". Each case is
parametrised per generated voice, so a homophone that only one voice trips
still shows up.

Run post-reboot, GPU live:
    poetry run python scripts/gen_codeswitch_wavs.py   # once, CPU
    poetry run pytest tests/test_codeswitch_eval.py -m gpu -v
"""

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from tuparles.eval import score_case
from tuparles.pipeline import postprocess

pytestmark = pytest.mark.gpu

DATA = Path(__file__).parent / "data" / "codeswitch"
WAV_DIR = DATA / "wav"
MANIFEST = WAV_DIR / "manifest.json"
CORPUS = DATA / "corpus.json"


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    return json.loads(MANIFEST.read_text()).get("files", [])


CASES_BY_ID = {
    c["id"]: c for c in json.loads(CORPUS.read_text())["cases"]
}
ENTRIES = _load_manifest()

requires_gpu = pytest.mark.skipif(
    not _cuda_available(), reason="no CUDA device (run on the GPU box)"
)
requires_wavs = pytest.mark.skipif(
    not ENTRIES, reason="no WAVs — run scripts/gen_codeswitch_wavs.py first"
)


def _read_wav_int16(path: Path) -> np.ndarray:
    """16 kHz mono s16 WAV → int16 array, exactly what GpuEngine expects."""
    with wave.open(str(path), "rb") as wav:
        assert wav.getframerate() == 16_000, f"{path.name}: not 16 kHz"
        assert wav.getnchannels() == 1, f"{path.name}: not mono"
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype=np.int16)


@pytest.fixture(scope="session")
def engine():
    from tuparles.engine import GpuEngine

    return GpuEngine()


@requires_gpu
@requires_wavs
@pytest.mark.parametrize(
    "entry", ENTRIES, ids=[e["file"] for e in ENTRIES]
)
def test_codeswitch_case(engine, entry, record_property):
    case = CASES_BY_ID[entry["case_id"]]
    audio = _read_wav_int16(WAV_DIR / entry["file"])

    raw = engine.transcribe(audio).text
    text = postprocess(raw)
    result = score_case(case, text)

    # WER is recorded as a trend signal even on pass (visible with -v / junitxml)
    record_property("wer", round(result.wer, 3))
    record_property("voice", entry["voice"])
    record_property("hypothesis", text)

    assert result.passed, (
        f"\n  case   : {case['id']} ({entry['voice']})"
        f"\n  said   : {case['text']}"
        f"\n  heard  : {text!r}"
        f"\n  missing: {result.missing}"
        f"\n  leaked : {result.leaked}"
        f"\n  wer    : {result.wer:.2f}"
    )
