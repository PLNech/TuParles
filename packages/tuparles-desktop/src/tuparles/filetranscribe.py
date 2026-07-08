"""Offline file transcription — the engine behind `tuparles transcribe FILE …`.

Distinct from the realtime daemon engine on purpose:

- whole-file, not a growing live buffer;
- batched + VAD, so a 30-minute meeting decodes in ~seconds-per-minute-of-audio
  instead of linearly, and long silences are skipped;
- keeps per-segment timestamps (the daemon throws them away after joining).

It degrades GPU-or-CPU like everything else — large-v3-turbo on CUDA, a CT2
int8 model on CPU — but never through the qwen binary: that decodes a whole
file in one subprocess with a 120 s timeout and emits no timestamps, which is
the wrong tool for a long recording. ffmpeg does the demux/resample so any
audio (or video) container it understands is fair game, not just 16 kHz WAV.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tuparles import settings
from tuparles.config import SAMPLE_RATE
from tuparles.engine import (
    _preload_cuda_libs,
    _vocab_prompt,
    decode_language_opts,
)

# CPU fallback model: `small` (not the realtime `base`) — a kept transcript is
# worth the extra quality, and offline we're not racing a live preview. Override
# with `--model`. GPU always uses turbo.
CPU_FILE_MODEL = "small"


@dataclass(frozen=True)
class Segment:
    """One VAD-delimited chunk of speech, with its wall-clock offsets."""

    start: float
    end: float
    text: str


def decode_to_pcm(path: Path) -> np.ndarray:
    """Any ffmpeg-readable media → float32 mono @ SAMPLE_RATE in [-1, 1].

    We let ffmpeg do the demux + downmix + resample (its `f32le` output is
    already normalized float), so a 48 kHz stereo AAC and a 16 kHz mono WAV
    arrive at the model identically. Raises RuntimeError with a human message
    if ffmpeg is missing or can't read the file.
    """
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-i",
                str(path),
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "-",
            ],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg introuvable — installe-le (`sudo apt install ffmpeg`)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        msg = exc.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = msg[-1] if msg else "raison inconnue"
        raise RuntimeError(f"ffmpeg n'a pas pu lire {path.name} : {tail}") from exc
    return np.frombuffer(proc.stdout, dtype=np.float32)


def pick_device(prefer: str = "auto") -> tuple[str, str, str]:
    """(device, compute_type, default_model) for the requested preference.

    `auto` uses the GPU when torch reports a CUDA device, else CPU — the same
    "GPU if it answers, CPU otherwise" rule the daemon follows.
    """
    if prefer == "cpu":
        return "cpu", "int8", CPU_FILE_MODEL
    want_gpu = prefer == "cuda"
    if prefer == "auto":
        try:
            import torch

            want_gpu = torch.cuda.is_available()
        except Exception:
            want_gpu = False
    if want_gpu:
        return "cuda", "float16", "large-v3-turbo"
    return "cpu", "int8", CPU_FILE_MODEL


class FileTranscriber:
    """A loaded batched Whisper pipeline for offline files.

    Load once (`FileTranscriber(...)`), transcribe many files. Language handling
    mirrors the daemon: the user's `languages` setting drives forced/auto/
    per-segment (`multilingual`) detection, so mid-sentence code-switching in a
    meeting survives. The personal glossary rides `initial_prompt` too.
    """

    def __init__(self, device: str = "auto", model: str | None = None) -> None:
        dev, compute, default_model = pick_device(device)
        try:
            self._load(dev, compute, model or default_model)
        except Exception as exc:
            # GPU-or-CPU, never GPU-or-nothing (the same self-heal the daemon's
            # ResilientEngine does): a wedged CUDA context — e.g. after a
            # suspend/resume — must not sink the whole transcription. On an
            # explicit `--device cuda` we respect the ask and re-raise; on `auto`
            # / `cuda`-by-default we fall back to CPU with a visible warning.
            if dev != "cuda" or device == "cuda":
                raise
            import sys

            print(
                f"GPU indisponible ({str(exc)[:120]}) — repli sur CPU.",
                file=sys.stderr,
            )
            cpu_dev, cpu_compute, cpu_model = pick_device("cpu")
            self._load(cpu_dev, cpu_compute, model or cpu_model)

    def _load(self, dev: str, compute: str, model_name: str) -> None:
        self.device = dev
        self.model_name = model_name
        if dev == "cuda":
            _preload_cuda_libs()
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        self._model = WhisperModel(model_name, device=dev, compute_type=compute)
        self._batched = BatchedInferencePipeline(model=self._model)

    def transcribe(self, pcm, progress=None) -> tuple[list[Segment], object]:
        """float32 PCM → (segments, info). `progress(end_seconds)` fires as each
        segment lands, so a caller can render a running percentage."""
        language, multilingual = decode_language_opts(settings.get("languages") or [])
        segments, info = self._batched.transcribe(
            pcm,
            batch_size=16,
            beam_size=5,
            vad_filter=True,
            initial_prompt=_vocab_prompt(),
            language=language,
            multilingual=multilingual,
        )
        out: list[Segment] = []
        for seg in segments:  # generator: consuming it drives the decode
            out.append(Segment(seg.start, seg.end, seg.text.strip()))
            if progress is not None:
                progress(seg.end)
        return out, info


def format_ts(seconds: float) -> str:
    """Seconds → `mm:ss`, or `h:mm:ss` past the hour."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_transcript(
    segments: list[Segment],
    *,
    source: str,
    model: str,
    device: str,
    duration: float,
    date: str,
) -> str:
    """Segments → the `[mm:ss] text` transcript body, with a one-line provenance
    header. Each line gets the deterministic lexicon (known mishears) but no
    spoken-punctuation / repeat-collapse / command parsing — a meeting is not a
    dictation, so we stay faithful to what was said."""
    from tuparles.lexicon import apply_lexicon

    lines = [
        f"# {source}  ·  {format_ts(duration)}  ·  {model} ({device})  ·  {date}",
        "",
    ]
    for seg in segments:
        text = apply_lexicon(seg.text)
        if text:
            lines.append(f"[{format_ts(seg.start)}] {text}")
    return "\n".join(lines) + "\n"
