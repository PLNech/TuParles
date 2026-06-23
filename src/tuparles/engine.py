"""Transcription engines.

Primary: faster-whisper large-v3-turbo, float16, persistent on the RTX 4080
(~0.5-1 s per utterance, 29x realtime measured — see docs/spike-backend.md).
Fallback: the vendored qwen-asr C binary on CPU, for when the GPU is
unavailable (driver issues, VRAM pressure).
"""

import ctypes
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tuparles import settings
from tuparles.config import (
    QWEN_BINARY,
    QWEN_MODEL_DIR,
    QWEN_THREADS,
    SAMPLE_RATE,
    VOCAB_FILE,
)
from tuparles.languages import snap_language
from tuparles.preprocess import normalize_audio


@dataclass
class Transcription:
    """Final-decode result: text + the metadata engines used to discard."""

    text: str
    language: str | None = None
    language_prob: float | None = None


def _vocab_prompt() -> str | None:
    """Personal glossary → initial_prompt. Whisper treats it as preceding
    context, which measurably biases decoding toward these spellings."""
    if not VOCAB_FILE.exists():
        return None
    words = [
        w.strip()
        for w in VOCAB_FILE.read_text().splitlines()
        if w.strip() and not w.lstrip().startswith("#")
    ]
    return f"Glossaire : {', '.join(words)}." if words else None


def _preload_cuda_libs() -> None:
    """CT2 dlopens cuBLAS/cuDNN at runtime; the pip wheels aren't on the
    loader path, so map them in explicitly before faster_whisper imports."""
    import nvidia.cublas.lib
    import nvidia.cudnn.lib

    for mod in (nvidia.cublas.lib, nvidia.cudnn.lib):
        libdir = Path(list(mod.__path__)[0])
        for so in sorted(libdir.glob("*.so*")):
            try:
                ctypes.CDLL(str(so), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


class GpuEngine:
    """Persistent large-v3-turbo on CUDA. Load once (~1.6 s), decode forever."""

    supports_partials = True

    def __init__(self) -> None:
        _preload_cuda_libs()
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        self._model = WhisperModel(
            "large-v3-turbo", device="cuda", compute_type="float16"
        )
        # Final decodes go through the batched pipeline: VAD splits the take
        # into chunks decoded in parallel on the GPU. On long takes this is
        # the difference between ~linear-in-length and ~seconds (the "1 min
        # frozen after a long dictation" bug); on short takes it's a no-op.
        self._batched = BatchedInferencePipeline(model=self._model)

    def transcribe(self, audio: np.ndarray) -> Transcription:
        """int16 mono 16 kHz → full-quality beam decode, batched."""
        if audio.size == 0:
            return Transcription("")
        pcm = normalize_audio(audio.astype(np.float32) / 32768.0)
        segments, info = self._batched.transcribe(
            pcm,
            batch_size=16,
            beam_size=5,
            vad_filter=True,
            # Re-read per decode: `tuparles vocab add` applies to the next
            # take, no restart (like the language setting).
            initial_prompt=_vocab_prompt(),
            language=self._constrain_language(pcm),
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcription(
            text,
            language=getattr(info, "language", None),
            language_prob=getattr(info, "language_probability", None),
        )

    def _constrain_language(self, pcm: np.ndarray) -> str | None:
        """Apply the user's language selection (settings, hot-reloaded).

        None = auto-detect. One selected = forced. Several = detect then
        snap to the most probable selected one — an extra encoder pass on
        one 30 s window, ~tens of ms on GPU.
        """
        selected = settings.get("languages") or []
        if not selected:
            return None
        if len(selected) == 1:
            return selected[0]
        try:
            _, _, all_probs = self._model.detect_language(pcm)
            return snap_language(all_probs or [], selected)
        except Exception:
            return None  # detector hiccup → auto, never block the take

    def transcribe_partial(self, audio: np.ndarray) -> str:
        """Fast greedy decode of the growing buffer for live partials.

        beam_size=1 halves latency; condition_on_previous_text=False keeps
        each partial independent so a mishear can't snowball across calls.
        The final transcribe() re-decodes everything with the full beam.

        No initial_prompt here: greedy decodes on short audio love to echo
        the prompt verbatim ("Glossaire : …" flashing in the bubble). The
        vocabulary bias only needs to land on the final decode.
        """
        if audio.size == 0:
            return ""
        pcm = normalize_audio(audio.astype(np.float32) / 32768.0)
        segments, _ = self._model.transcribe(
            pcm,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
            language=self._constrain_language(pcm),
        )
        return " ".join(s.text.strip() for s in segments).strip()


class QwenCpuEngine:
    """Fallback: vendored qwen-asr C binary, fresh process per utterance
    (weights are mmap'd, spawn costs ~0.65 s)."""

    # Re-decoding a growing buffer at ~0.4x realtime would fall behind
    # within seconds (see docs/spike-backend.md) — waveform-only bubble.
    supports_partials = False

    def transcribe(self, audio: np.ndarray) -> Transcription:
        if audio.size == 0:
            return Transcription("")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            _write_wav(Path(tmp.name), audio)
            result = subprocess.run(
                [
                    str(QWEN_BINARY),
                    "-d", str(QWEN_MODEL_DIR),
                    "-i", tmp.name,
                    "-t", str(QWEN_THREADS),
                    "--silent",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        if result.returncode != 0:
            raise RuntimeError(f"qwen_asr failed: {result.stderr.strip()[:500]}")
        return Transcription(result.stdout.strip())


def load_engine():
    """GPU if it answers, CPU fallback otherwise. Never crash at startup."""
    try:
        return GpuEngine()
    except Exception as exc:
        print(f"GPU engine unavailable ({exc}); falling back to qwen-asr CPU")
        return QwenCpuEngine()


def _write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio.astype(np.int16).tobytes())
