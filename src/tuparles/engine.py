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
from pathlib import Path

import numpy as np

from tuparles.config import (
    QWEN_BINARY,
    QWEN_MODEL_DIR,
    QWEN_THREADS,
    SAMPLE_RATE,
    VOCAB_FILE,
)


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
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            "large-v3-turbo", device="cuda", compute_type="float16"
        )
        self._prompt = _vocab_prompt()

    def transcribe(self, audio: np.ndarray) -> str:
        """int16 mono 16 kHz → text. Safe to call repeatedly on a growing
        buffer for live partials (~0.5-1 s per call)."""
        if audio.size == 0:
            return ""
        pcm = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            pcm, beam_size=5, vad_filter=True, initial_prompt=self._prompt
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe_partial(self, audio: np.ndarray) -> str:
        """Fast greedy decode of the growing buffer for live partials.

        beam_size=1 halves latency; condition_on_previous_text=False keeps
        each partial independent so a mishear can't snowball across calls.
        The final transcribe() re-decodes everything with the full beam.
        """
        if audio.size == 0:
            return ""
        pcm = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            pcm,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=self._prompt,
        )
        return " ".join(s.text.strip() for s in segments).strip()


class QwenCpuEngine:
    """Fallback: vendored qwen-asr C binary, fresh process per utterance
    (weights are mmap'd, spawn costs ~0.65 s)."""

    # Re-decoding a growing buffer at ~0.4x realtime would fall behind
    # within seconds (see docs/spike-backend.md) — waveform-only bubble.
    supports_partials = False

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
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
        return result.stdout.strip()


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
