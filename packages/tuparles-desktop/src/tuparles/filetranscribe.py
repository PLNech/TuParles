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
class Word:
    """One decoded word with its wall-clock span — the raw material for the
    turn-seam heuristic (`render_transcript`). Mirrors faster-whisper's own
    `Word` (start/end/word) minus the probability we don't use here."""

    start: float
    end: float
    word: str


@dataclass(frozen=True)
class Segment:
    """One VAD-delimited chunk of speech, with its wall-clock offsets.

    `words` carries per-word timings when the decode ran with word-level
    timestamps (the offline default), else None — the turn-seam split degrades
    to segment-boundary gaps only when it's absent (never crashes)."""

    start: float
    end: float
    text: str
    words: tuple[Word, ...] | None = None


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

    `auto` uses the GPU when a CUDA device answers, else CPU — the same
    "GPU if it answers, CPU otherwise" rule the daemon follows.

    We probe via ctranslate2, not torch: ct2 is what actually decodes here, and
    torch was pulling in ~2 GB of wheels for a single boolean — a lean-install /
    mobile portability blocker and a slow import. This mirrors the eval harness's
    `_cuda_available()` probe (tests/test_codeswitch_eval.py).
    """
    if prefer == "cpu":
        return "cpu", "int8", CPU_FILE_MODEL
    want_gpu = prefer == "cuda"
    if prefer == "auto":
        try:
            import ctranslate2

            want_gpu = ctranslate2.get_cuda_device_count() > 0
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
        # Remember an explicit `--model`: on a decode-time CPU fallback we honour
        # a forced model but otherwise drop to the CPU default (turbo won't fit /
        # perform on CPU). None == "user didn't force one".
        self._model_override = model
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
        segment lands, so a caller can render a running percentage.

        Guarded against a decode-time CUDA wedge, not just a load-time one:
        after suspend/resume ct2 reports the GPU available and the model *loads*
        fine, then the lazy segment generator throws mid-drain (see
        ResilientEngine's docstring). `__init__` already self-heals on load
        failure, but a 28-minute transcription must not sink on the first bad
        `next()` either. So on a CUDA decode failure we reload on CPU and restart
        from zero — offline has no partial-progress contract, so a progress
        callback simply starts over, which is acceptable. If we're already on
        CPU there's nowhere left to fall back to, so we re-raise.
        """
        try:
            return self._decode(pcm, progress)
        except Exception as exc:
            if self.device != "cuda":
                raise
            import sys

            print(
                f"GPU indisponible en cours de décodage ({str(exc)[:120]}) — "
                "repli sur CPU.",
                file=sys.stderr,
            )
            cpu_dev, cpu_compute, cpu_model = pick_device("cpu")
            # Honour an explicit `--model`; otherwise take the CPU default.
            self._load(cpu_dev, cpu_compute, self._model_override or cpu_model)
            return self._decode(pcm, progress)

    def _decode(self, pcm, progress=None) -> tuple[list[Segment], object]:
        """The actual decode + generator drain — factored out so transcribe()
        can retry the whole thing on a fresh (CPU) pipeline after a GPU wedge."""
        language, multilingual = decode_language_opts(settings.get("languages") or [])
        segments, info = self._batched.transcribe(
            pcm,
            batch_size=16,
            beam_size=5,
            vad_filter=True,
            # Word-level timings power the turn-seam heuristic (render_transcript):
            # a long word-to-word gap inside a fused block is a likely turn change.
            # If the engine can't supply them, `seg.words` is None and the seam
            # logic degrades to segment-boundary gaps only — never GPU-or-nothing.
            word_timestamps=True,
            initial_prompt=_vocab_prompt(),
            language=language,
            multilingual=multilingual,
        )
        out: list[Segment] = []
        for seg in segments:  # generator: consuming it drives the decode
            raw_words = getattr(seg, "words", None)
            words = (
                tuple(Word(w.start, w.end, w.word) for w in raw_words)
                if raw_words
                else None
            )
            out.append(Segment(seg.start, seg.end, seg.text.strip(), words))
            if progress is not None:
                progress(seg.end)
        return out, info


def format_ts(seconds: float) -> str:
    """Seconds → `mm:ss`, or `h:mm:ss` past the hour."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


TURN_SEAM = "— "  # visible, unlabelled turn boundary (language-neutral, FR-natural)


def _split_at_gaps(seg: Segment, threshold: float) -> list[tuple[float, str]]:
    """Split one segment into (start, text) blocks at internal word-gaps above
    `threshold` seconds. The first block keeps the segment's natural start; each
    later block starts at the first word after a long silence — a likely turn
    change. Degrades to a single block (the whole segment) when word timings are
    absent or splitting is disabled (`threshold <= 0`), so the caller's output is
    unchanged in those cases."""
    if threshold <= 0 or not seg.words:
        return [(seg.start, seg.text)]
    blocks: list[tuple[float, str]] = []
    cur: list[Word] = []
    prev_end: float | None = None
    for w in seg.words:
        if prev_end is not None and (w.start - prev_end) > threshold:
            blocks.append((cur[0].start, "".join(x.word for x in cur).strip()))
            cur = []
        cur.append(w)
        prev_end = w.end
    if cur:
        blocks.append((cur[0].start, "".join(x.word for x in cur).strip()))
    return blocks


def render_transcript(
    segments: list[Segment],
    *,
    source: str,
    model: str,
    device: str,
    duration: float,
    date: str,
    turn_gap: float | None = None,
) -> str:
    """Segments → the `[mm:ss] text` transcript body, with a one-line provenance
    header. Each line gets the deterministic lexicon (known mishears) but no
    spoken-punctuation / repeat-collapse / command parsing — a meeting is not a
    dictation, so we stay faithful to what was said.

    Turn seams: a silence gap longer than `turn_gap` seconds — inside a
    fused segment (via word timings) or across a segment boundary — splits the
    block and marks the new turn with a leading "— ", so three speakers' fused
    sentences read as three visibly separate turns rather than one train of
    thought. `turn_gap=None` reads the `turn_gap_s` setting (default 1.2); 0
    disables the split entirely (byte-identical to the pre-seam output). This is
    a boundary a reader can see, not diarization — no speaker identity attached.
    """
    from tuparles.lexicon import apply_lexicon

    if turn_gap is None:
        turn_gap = settings.get("turn_gap_s")
    threshold = float(turn_gap or 0.0)

    lines = [
        f"# {source}  ·  {format_ts(duration)}  ·  {model} ({device})  ·  {date}",
        "",
    ]
    prev_end: float | None = None
    for seg in segments:
        for i, (start, raw) in enumerate(_split_at_gaps(seg, threshold)):
            text = apply_lexicon(raw)
            if not text:
                continue
            # A seam prefixes any post-split continuation (i > 0) and any first
            # block that opens after a long gap from the previous segment.
            seam = threshold > 0 and (
                i > 0 or (prev_end is not None and (start - prev_end) > threshold)
            )
            prefix = TURN_SEAM if seam else ""
            lines.append(f"[{format_ts(start)}] {prefix}{text}")
        prev_end = seg.end
    return "\n".join(lines) + "\n"
