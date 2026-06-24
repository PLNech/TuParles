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
)
from tuparles.preprocess import normalize_audio


@dataclass
class Transcription:
    """Final-decode result: text + the metadata engines used to discard."""

    text: str
    language: str | None = None
    language_prob: float | None = None


def decode_language_opts(selected: list[str]) -> tuple[str | None, bool]:
    """Map the user's language selection to faster-whisper's
    (language, multilingual) arguments.

    0 selected → (None, False): detect once among all languages.
    1 selected → (code, False): forced — the user wants only this one.
    2+ selected → (None, True): per-segment language detection, so
        mid-sentence code-switching survives. This is the whole reason
        TuParles exists. Forcing one language frenchifies/anglicizes the
        others ("can I switch to English" → "peux-je changer en anglais");
        detect-then-snap had the same flaw — one language for the whole take.
        multilingual=True lets large-v3 follow the switch segment by segment.
        Trade-off: per-segment detection can rarely mis-pick on a short/noisy
        chunk, but for a code-switcher that beats mangling a whole language.
    """
    if len(selected) == 1:
        return selected[0], False
    return None, len(selected) >= 2


def _vocab_prompt() -> str | None:
    """Personal glossary (+ opt-in codebase dict-seeds) → initial_prompt. Whisper
    treats it as preceding context, which measurably biases decoding toward these
    spellings. The merge + dict-seed feed live in `seed_prompt` (#68)."""
    from tuparles import seed_prompt

    return seed_prompt.initial_prompt()


def _preload_cuda_libs() -> None:
    """CT2 dlopens cuBLAS/cuDNN at runtime; the pip wheels aren't on the
    loader path, so map them in explicitly before faster_whisper imports."""
    import nvidia.cublas.lib
    import nvidia.cudnn.lib

    for mod in (nvidia.cublas.lib, nvidia.cudnn.lib):
        libdir = Path(next(iter(mod.__path__)))
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
        language, multilingual = self._decode_language_opts()
        segments, info = self._batched.transcribe(
            pcm,
            batch_size=16,
            beam_size=5,
            vad_filter=True,
            # Re-read per decode: `tuparles vocab add` applies to the next
            # take, no restart (like the language setting).
            initial_prompt=_vocab_prompt(),
            language=language,
            multilingual=multilingual,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcription(
            text,
            language=getattr(info, "language", None),
            language_prob=getattr(info, "language_probability", None),
        )

    def _decode_language_opts(self) -> tuple[str | None, bool]:
        """(language, multilingual) from the user's selection, hot-reloaded."""
        return decode_language_opts(settings.get("languages") or [])

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
        language, multilingual = self._decode_language_opts()
        segments, _ = self._model.transcribe(
            pcm,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
            language=language,
            multilingual=multilingual,
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
                    "-d",
                    str(QWEN_MODEL_DIR),
                    "-i",
                    tmp.name,
                    "-t",
                    str(QWEN_THREADS),
                    "--silent",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        if result.returncode != 0:
            raise RuntimeError(f"qwen_asr failed: {result.stderr.strip()[:500]}")
        return Transcription(result.stdout.strip())


class ResilientEngine:
    """GPU engine with mid-session recovery.

    A laptop suspend/resume invalidates the CUDA context: the model loads
    fine at startup and decodes for hours, then every decode throws after a
    sleep (the daemon holds a stale context even though `nvidia-smi` and
    fresh processes are fine). The old design only fell back to CPU at *load*
    time, so a post-resume context death meant every take silently yielded
    nothing.

    On a decode failure we rebuild the GPU engine once — a fresh CUDA context
    in the same process (~1.6 s), which is exactly what recovers from
    suspend/resume — and retry. Only if that also fails is the GPU genuinely
    gone, so we drop to qwen-CPU for the rest of the session. Either way a
    take never silently produces nothing.

    Factories are injectable so the recovery logic is testable without a GPU.
    """

    def __init__(self, gpu_factory=GpuEngine, cpu_factory=QwenCpuEngine) -> None:
        self._gpu_factory = gpu_factory
        self._cpu_factory = cpu_factory
        self._gpu = gpu_factory()  # may raise — load_engine() handles it
        self._cpu = None  # built lazily, only if the GPU truly dies
        self._on_cpu = False

    @property
    def engine_name(self) -> str:
        """Backend that actually served the last decode (for telemetry)."""
        return "QwenCpuEngine" if self._on_cpu else "GpuEngine"

    @property
    def supports_partials(self) -> bool:
        return not self._on_cpu and self._gpu is not None

    def transcribe(self, audio: np.ndarray) -> Transcription:
        if self._on_cpu:
            return self._cpu_engine().transcribe(audio)
        try:
            return self._gpu.transcribe(audio)
        except Exception as exc:
            print(f"GPU decode failed ({str(exc)[:120]}); rebuilding CUDA context")
            if self._rebuild_gpu():
                try:
                    return self._gpu.transcribe(audio)
                except Exception as exc2:
                    print(f"GPU still failing ({str(exc2)[:120]}); CPU fallback")
            self._on_cpu = True
            return self._cpu_engine().transcribe(audio)

    def transcribe_partial(self, audio: np.ndarray) -> str:
        # Partials are frequent and best-effort: never rebuild on one (it would
        # thrash), never fall back — let the final transcribe() drive recovery.
        if self._on_cpu or self._gpu is None:
            return ""
        try:
            return self._gpu.transcribe_partial(audio)
        except Exception:
            return ""

    def _rebuild_gpu(self) -> bool:
        try:
            self._gpu = self._gpu_factory()
            return True
        except Exception:
            self._gpu = None
            return False

    def _cpu_engine(self):
        if self._cpu is None:
            self._cpu = self._cpu_factory()
        return self._cpu


def load_engine():
    """GPU (self-healing) if it answers, CPU fallback otherwise. Never crash
    at startup, and never get stuck with no STT after a suspend/resume."""
    try:
        return ResilientEngine()
    except Exception as exc:
        print(f"GPU engine unavailable ({exc}); falling back to qwen-asr CPU")
        return QwenCpuEngine()


def _write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio.astype(np.int16).tobytes())
