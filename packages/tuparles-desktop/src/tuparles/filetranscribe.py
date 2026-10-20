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

Two outputs, one story: `render_transcript` writes the human `[mm:ss] text`
body and `render_json` writes a machine-readable sidecar (schema_version 1) at
the SAME block granularity (post turn-seam split), so the two never diverge.
The JSON carries what the txt throws away — per-word probabilities, per-segment
QC (avg_logprob / no_speech_prob / compression_ratio), turn-seam flags — and
invents nothing: a value the decode didn't supply is `null`, never guessed.

`speakers` is a deliberate `null` placeholder: diarization lands there later as
`{"SPEAKER_00": {"talk_s": ...}}` plus a per-message `"speaker"` annotation.
Both are pure additions (a new top-level value in place of null, a new key in
an existing annotations dict), so a consumer written against v1 keeps working —
the schema is designed for that growth without a version bump breaking readers.
"""

import logging
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from tuparles import settings
from tuparles.config import SAMPLE_RATE
from tuparles.engine import (
    TUNED_VAD_PARAMETERS,
    _preload_cuda_libs,
    _vocab_prompt,
    cpu_preference,
    decode_language_opts,
)
from tuparles.preprocess import (
    SilenceVerdict,
    default_speech_detectors,
    prepare_pcm,
    silence_gate,
)
from tuparles.repeats import cut_loops

_log = logging.getLogger("tuparles.filetranscribe")

# CPU fallback model: `small` (not the realtime `base`) — a kept transcript is
# worth the extra quality, and offline we're not racing a live preview. Override
# with `--model`. GPU always uses turbo.
CPU_FILE_MODEL = "small"


@dataclass(frozen=True)
class Word:
    """One decoded word with its wall-clock span. Mirrors faster-whisper's own
    `Word` (start/end/word/probability): `word` timings drive the turn-seam
    heuristic (`render_transcript`); `p` (the model's per-word probability, None
    when the engine didn't supply one) surfaces in the JSON sidecar so a reader
    can spot a shaky word. `p` is trailing + optional so positional construction
    (`Word(s, e, w)`) still works."""

    start: float
    end: float
    word: str
    p: float | None = None


@dataclass(frozen=True)
class Segment:
    """One VAD-delimited chunk of speech, with its wall-clock offsets.

    `words` carries per-word timings when the decode ran with word-level
    timestamps (the offline default), else None — the turn-seam split degrades
    to segment-boundary gaps only when it's absent (never crashes).

    The trailing QC fields mirror faster-whisper's own per-segment metrics
    (`avg_logprob`, `no_speech_prob`, `compression_ratio`) — captured for the
    JSON sidecar's `low_confidence` heuristic, None when unknown. All are
    trailing + optional so positional construction (`Segment(s, e, text)` or
    `Segment(s, e, text, words)`) still works and the `_FakeSeg` decode fakes,
    which carry none of them, degrade to None via getattr defaults.

    `repetition` is set only by `guard_repetition` (#54): (phrase, copies) of a
    decode loop it cut down to one copy in this segment, else None;
    `repetition_at` is how many of the segment's tokens (words when timed,
    else whitespace tokens) come before the cut, where the txt puts its
    `[…×N]` marker."""

    start: float
    end: float
    text: str
    words: tuple[Word, ...] | None = None
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    repetition: tuple[str, int] | None = None
    repetition_at: int | None = None


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
    "GPU if it answers, CPU otherwise" rule the daemon follows, and it honours
    the same `prefer_cpu` setting: a batch transcription is precisely when
    you'd notice the card being taken out from under whoever else wants it. It
    honours `battery_aware` too (CPU while discharging), via the same
    `cpu_preference()` the daemon's engine reads. An explicit `--device cuda`
    still wins, because a flag you just typed beats a preference you once set.

    We probe via ctranslate2, not torch: ct2 is what actually decodes here, and
    torch was pulling in ~2 GB of wheels for a single boolean — a lean-install /
    mobile portability blocker and a slow import. This mirrors the eval harness's
    `_cuda_available()` probe (tests/test_codeswitch_eval.py).
    """
    if prefer == "cpu":
        return "cpu", "int8", CPU_FILE_MODEL
    want_gpu = prefer == "cuda"
    if prefer == "auto":
        # Ahead of the probe on purpose: the preferred path then never imports
        # ctranslate2 at all, which is also a faster start.
        if cpu_preference():
            return "cpu", "int8", CPU_FILE_MODEL
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
        # Same "prepare PCM for decode" seam the daemon engines use (#131): the
        # ffmpeg f32le output is normalized level, but DC-removal + peak-normalize
        # here keeps the offline path from silently diverging from the live one.
        # Idempotent enough that transcribe()'s GPU-wedge retry can re-run it.
        pcm = prepare_pcm(pcm)
        segments, info = self._batched.transcribe(
            pcm,
            batch_size=16,
            beam_size=5,
            vad_filter=True,
            # A COPY: BatchedInferencePipeline pops "max_speech_duration_s" off
            # the dict it is handed (faster-whisper 1.2.1), which would strip it
            # from the shared module-level params for every later caller.
            vad_parameters=dict(TUNED_VAD_PARAMETERS),
            # No condition_on_previous_text / compression_ratio_threshold /
            # no_speech_threshold here: the batched pipeline hardcodes the first
            # to False and never acts on the other two (no temperature fallback,
            # no segment skip), so passing them would only look like a guard.
            # The loop guard is `guard_repetition`, after the decode (#54).
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
                tuple(
                    Word(w.start, w.end, w.word, getattr(w, "probability", None))
                    for w in raw_words
                )
                if raw_words
                else None
            )
            # QC metrics via getattr: real faster-whisper segments carry them;
            # the _FakeSeg decode fakes don't, and degrade to None (no crash).
            out.append(
                Segment(
                    seg.start,
                    seg.end,
                    seg.text.strip(),
                    words,
                    avg_logprob=getattr(seg, "avg_logprob", None),
                    no_speech_prob=getattr(seg, "no_speech_prob", None),
                    compression_ratio=getattr(seg, "compression_ratio", None),
                )
            )
            if progress is not None:
                progress(seg.end)
        return out, info


# --- near-silence: the silence gate + the loop guard (#54) -------------------

# BatchedInferencePipeline overrides the VAD's max_speech_duration_s with the
# model's chunk length; every Whisper model's feature extractor uses 30 s.
_DECODER_VAD_MAX_SPEECH_S = 30


def _decoder_vad_span(audio_f: np.ndarray, sample_rate: int) -> tuple[int, int] | None:
    """The decoder's OWN speech detector, as a gate tier: faster-whisper's
    bundled silero VAD (ONNX, CPU) with the same parameters, on the same
    `prepare_pcm` output `_decode` hands the batched pipeline. So when this
    says "no speech", the decode would have had zero audio to work on and
    returned nothing: on the file path the gate can never cost a transcript.
    Raises ImportError without faster-whisper (the gate then falls through to
    the trim tiers)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    params = {
        k: v for k, v in TUNED_VAD_PARAMETERS.items() if k != "max_speech_duration_s"
    }
    opts = VadOptions(**params, max_speech_duration_s=_DECODER_VAD_MAX_SPEECH_S)
    ts = get_speech_timestamps(prepare_pcm(audio_f), opts, sampling_rate=sample_rate)
    if not ts:
        return None
    return int(ts[0]["start"]), int(ts[-1]["end"])


def check_silence(pcm: np.ndarray) -> SilenceVerdict:
    """The pre-decode silence gate for one file (see `preprocess.silence_gate`),
    with the decoder's own VAD as first detector. Every verdict is logged with
    its levels — a skipped file is the one a reader will ask about."""
    verdict = silence_gate(
        pcm,
        SAMPLE_RATE,
        detectors=[
            ("faster-whisper-vad", _decoder_vad_span),
            *default_speech_detectors(),
        ],
    )
    _log.info(
        "silence gate: %s (%s, detector=%s, floor=%s dBFS, level=%s dBFS, "
        "peak=%s dBFS, active=%.2fs)",
        "GATED" if verdict.gated else "decode",
        verdict.reason,
        verdict.detector,
        verdict.floor_dbfs,
        verdict.level_dbfs,
        verdict.peak_dbfs,
        verdict.active_s,
    )
    return verdict


def guard_repetition(segments: list[Segment]) -> list[Segment]:
    """Cut decode loops down to one copy (#54). The rule lives in
    `repeats.find_loop` (a phrase repeated verbatim 8+ times over 16+ words);
    here it runs over the whole decode as ONE word stream, so a loop that
    Whisper split into many one-phrase segments is caught too.

    Word timings ride along: a cut segment keeps the words it kept, its `end`
    moves to the last kept word, segments left empty disappear, and the
    segment holding the end of the surviving copy carries
    `repetition=(phrase, copies)` and `repetition_at` (its tokens before the
    cut).
    Without word timings the text is split on whitespace and the span is left
    as decoded. Untouched input comes back as the same objects."""
    tokens: list[str] = []
    owner: list[tuple[int, int]] = []
    per_seg: list[list[str]] = []
    for si, seg in enumerate(segments):
        toks = [w.word for w in seg.words] if seg.words else seg.text.split()
        per_seg.append(toks)
        for ti, tok in enumerate(toks):
            tokens.append(tok)
            owner.append((si, ti))
    kept, loops = cut_loops(tokens)
    if not loops:
        return list(segments)

    keep: list[set[int]] = [set() for _ in segments]
    for g in kept:
        si, ti = owner[g]
        keep[si].add(ti)
    flags: dict[int, tuple[str, int, int]] = {}
    for i, k, r in loops:
        phrase = " ".join(t.strip() for t in tokens[i : i + k])
        si, ti = owner[i + k - 1]  # the last token of the surviving copy
        flags.setdefault(si, (phrase, r, ti))

    out: list[Segment] = []
    for si, seg in enumerate(segments):
        toks = per_seg[si]
        if si not in flags and len(keep[si]) == len(toks):
            out.append(seg)  # untouched
            continue
        if not keep[si]:
            continue  # wholly inside a loop
        idx = sorted(keep[si])
        flag = flags.get(si)
        repetition = (flag[0], flag[1]) if flag else None
        at = idx.index(flag[2]) + 1 if flag else None
        if seg.words:
            words = tuple(seg.words[j] for j in idx)
            out.append(
                replace(
                    seg,
                    text="".join(w.word for w in words).strip(),
                    words=words,
                    end=words[-1].end,
                    repetition=repetition,
                    repetition_at=at,
                )
            )
        else:
            out.append(
                replace(
                    seg,
                    text=" ".join(toks[j] for j in idx),
                    repetition=repetition,
                    repetition_at=at,
                )
            )
    return out


def format_ts(seconds: float) -> str:
    """Seconds → `mm:ss`, or `h:mm:ss` past the hour."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


TURN_SEAM = "— "  # visible, unlabelled turn boundary (language-neutral, FR-natural)


def loop_mark(copies: int) -> str:
    """txt-only marker at a decode-loop cut (guard_repetition): ` […×12]`."""
    return f" […×{copies}]"


NO_SPEECH_NOTE = "aucune parole détectée"  # the txt's one-line verdict


@dataclass(frozen=True)
class _Block:
    """One rendered block: a whole segment, or a turn-split slice of one. Carries
    its own span + word subset (for the JSON sidecar's per-block word list and
    words_per_s), while its QC comes from the parent segment (shared across a
    segment's splits). `text` is raw (pre-lexicon); callers apply the lexicon."""

    start: float
    end: float
    text: str
    words: tuple[Word, ...] | None


def _mk_block(words: list[Word]) -> _Block:
    return _Block(
        words[0].start,
        words[-1].end,
        "".join(w.word for w in words).strip(),
        tuple(words),
    )


def _split_at_gaps(seg: Segment, threshold: float) -> list[_Block]:
    """Split one segment into blocks at internal word-gaps above `threshold`
    seconds. The first block keeps the segment's natural start; each later block
    starts at the first word after a long silence — a likely turn change.
    Degrades to a single block (the whole segment) when word timings are absent
    or splitting is disabled (`threshold <= 0`), so the caller's output is
    unchanged in those cases."""
    if threshold <= 0 or not seg.words:
        return [_Block(seg.start, seg.end, seg.text, seg.words)]
    blocks: list[_Block] = []
    cur: list[Word] = []
    prev_end: float | None = None
    for w in seg.words:
        if prev_end is not None and (w.start - prev_end) > threshold:
            blocks.append(_mk_block(cur))
            cur = []
        cur.append(w)
        prev_end = w.end
    if cur:
        blocks.append(_mk_block(cur))
    return blocks


def _iter_blocks(segments: list[Segment], threshold: float):
    """Walk segments → (seam, block, parent_segment) in render order. The single
    source of truth for block granularity + seam placement, so the txt body and
    the JSON sidecar can never tell two different stories. A seam opens on any
    post-split continuation (block index > 0) or a first block that starts more
    than `threshold` seconds after the previous segment ended."""
    prev_end: float | None = None
    for seg in segments:
        for i, blk in enumerate(_split_at_gaps(seg, threshold)):
            seam = threshold > 0 and (
                i > 0 or (prev_end is not None and (blk.start - prev_end) > threshold)
            )
            yield seam, blk, seg
        prev_end = seg.end


def render_transcript(
    segments: list[Segment],
    *,
    source: str,
    model: str,
    device: str,
    duration: float,
    date: str,
    turn_gap: float | None = None,
    note: str | None = None,
) -> str:
    """Segments → the `[mm:ss] text` transcript body, with a one-line provenance
    header. `note` adds a `# note` line under it (e.g. "aucune parole
    détectée", #54). Where `guard_repetition` cut a loop, `loop_mark` (` […×N]`,
    N = copies seen) sits right after the surviving copy, inside its block,
    with any real text that followed the loop after it. Each line gets the
    deterministic lexicon (known mishears) but no
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
    ]
    if note:
        lines.append(f"# {note}")
    lines.append("")
    for seam, blk, seg in _iter_blocks(segments, threshold):
        text = apply_lexicon(_marked_text(blk, seg))
        if not text:
            continue
        prefix = TURN_SEAM if seam else ""
        lines.append(f"[{format_ts(blk.start)}] {prefix}{text}")
    return "\n".join(lines) + "\n"


def _marked_text(blk: _Block, seg: Segment) -> str:
    """The block's raw text, with `loop_mark` inserted at the loop cut when
    the cut falls inside this block (#54). A timed block is a contiguous slice
    of its segment's words, located by identity; an untimed block is the
    whole segment, split on whitespace like guard_repetition split it."""
    if seg.repetition is None or seg.repetition_at is None:
        return blk.text
    mark = loop_mark(seg.repetition[1])
    if blk.words and seg.words:
        offset = next((i for i, w in enumerate(seg.words) if w is blk.words[0]), None)
        if offset is None:
            return blk.text
        j = seg.repetition_at - offset
        if not 0 < j <= len(blk.words):
            return blk.text
        head = "".join(w.word for w in blk.words[:j]).strip()
        tail = "".join(w.word for w in blk.words[j:]).strip()
    else:
        toks = blk.text.split()
        j = seg.repetition_at
        if not 0 < j <= len(toks):
            return blk.text
        head, tail = " ".join(toks[:j]), " ".join(toks[j:])
    return head + mark + (f" {tail}" if tail else "")


JSON_SCHEMA_VERSION = 1

# `low_confidence` floors — first-cut heuristics from a real-meeting QA pass
# (2026-07-08, local report) where a ~30 s block decoded to just 2 words: a
# block trips the flag when its per-segment avg_logprob is very low, the model
# thought it was mostly non-speech, or it decoded implausibly few words per
# second. Cheap, transparent, deterministic — the "cheap tier" QC of GH #31, not
# a learned confidence model. Each is None-safe: a metric the decode didn't
# supply simply can't trip its clause (we never invent a value to judge).
_LOW_AVG_LOGPROB = -1.0  # below this: the decode is unsure of the words
_HIGH_NO_SPEECH = 0.5  # above this: the model leaned "this isn't speech"
_LOW_WORDS_PER_S = 0.5  # below this: implausibly sparse for real speech


def _low_confidence(
    avg_logprob: float | None,
    no_speech_prob: float | None,
    words_per_s: float | None,
) -> bool:
    return bool(
        (avg_logprob is not None and avg_logprob < _LOW_AVG_LOGPROB)
        or (no_speech_prob is not None and no_speech_prob > _HIGH_NO_SPEECH)
        or (words_per_s is not None and words_per_s < _LOW_WORDS_PER_S)
    )


def _f(x: float | None) -> float | None:
    """None-safe cast to native float. faster-whisper hands timings/probabilities
    back as numpy scalars (np.float32), and a numpy comparison yields np.bool_ —
    json.dumps can serialize neither. We cast at the sidecar boundary, where the
    model outputs actually land, so the dict is native before it hits json."""
    return float(x) if x is not None else None


def _message(blk: _Block, seg: Segment, content: str, seam: bool) -> dict:
    """One block → a schema-v1 message. Per-block: span, word list, words_per_s.
    Shared-from-parent-segment: the QC metrics (a split block can't re-derive its
    own avg_logprob, so it repeats the segment's — documented, not invented)."""
    span = blk.end - blk.start
    n_words = len(blk.words) if blk.words is not None else None
    words_per_s = (
        round(n_words / span, 2) if (n_words is not None and span > 0) else None
    )
    words_json = (
        [
            {"w": w.word.strip(), "s": _f(w.start), "e": _f(w.end), "p": _f(w.p)}
            for w in blk.words
        ]
        if blk.words is not None
        else None
    )
    return {
        "start": _f(blk.start),
        "end": _f(blk.end),
        "content": content,
        "annotations": {
            "turn_seam": bool(seam),
            "avg_logprob": _f(seg.avg_logprob),
            "no_speech_prob": _f(seg.no_speech_prob),
            "compression_ratio": _f(seg.compression_ratio),
            "words_per_s": _f(words_per_s),
            "low_confidence": _low_confidence(
                seg.avg_logprob, seg.no_speech_prob, words_per_s
            ),
            # #54: a decode loop cut to one copy in this block's segment (shared
            # across its turn-seam splits, like the QC above), else null.
            "repetition": (
                {"phrase": seg.repetition[0], "copies": int(seg.repetition[1])}
                if seg.repetition
                else None
            ),
            "words": words_json,
        },
    }


def render_json(
    segments: list[Segment],
    *,
    source: str,
    model: str | None,  # None: no model ran (a file the silence gate skipped)
    device: str | None,
    duration: float,
    date: str,
    language: str | None = None,
    turn_gap: float | None = None,
    language_probability: float | None = None,
    no_speech: dict | None = None,
) -> dict:
    """Segments → the schema-v1 sidecar dict (see the module docstring for the
    shape and the diarization-ready `speakers` placeholder). `messages` are the
    SAME blocks `render_transcript` renders — post turn-seam split, empty blocks
    dropped, lexicon applied to `content` — via the shared `_iter_blocks`, so the
    two files tell one story. `turn_seam: true` marks a block the seam heuristic
    opened; the seam's visible "— " is a txt-only concern (content stays clean).
    `turn_gap=None` reads the `turn_gap_s` setting, matching the txt path.

    Invents nothing: `language` is `info.language` or None; per-segment QC and
    per-word `p` are passed straight through (None where the decode was silent);
    only `words_per_s` and `duration_s` are computed, and are None / rounded, not
    fabricated.

    #54 added three top-level keys, pure additions under schema v1:
    `language_probability` (the decoder's own detection confidence, or null),
    `no_speech` (null, or why the file has no messages: the silence gate's
    verdict + levels, or `{"reason": "decoder_empty"}`), and
    `truncated_repetition` (true when any message carries a `repetition`)."""
    from tuparles.lexicon import apply_lexicon

    if turn_gap is None:
        turn_gap = settings.get("turn_gap_s")
    threshold = float(turn_gap or 0.0)

    messages = []
    for seam, blk, seg in _iter_blocks(segments, threshold):
        content = apply_lexicon(blk.text)
        if not content:
            continue
        messages.append(_message(blk, seg, content, seam))

    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "source": source,
        "duration_s": round(duration, 1),
        "model": model,
        "device": device,
        "language": language,
        "language_probability": _f(language_probability),
        "created": date,
        "speakers": None,  # diarization lands here later (non-breaking; see docstring)
        "no_speech": no_speech,
        "truncated_repetition": any(s.repetition for s in segments),
        "messages": messages,
    }
