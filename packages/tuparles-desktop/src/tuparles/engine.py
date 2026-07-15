"""Transcription engines — the GPU→CPU gradient.

Primary: faster-whisper large-v3-turbo, float16, persistent on the RTX 4080
(~0.5-1 s per utterance, 29x realtime measured — see docs/spike-backend.md).
CPU rung (when the GPU is unavailable — driver issues, VRAM pressure, no card):
the promptable, portable `WhisperCppEngine` (whisper.cpp via pywhispercpp) when
it's installed, else the vendored qwen-asr C binary. whisper.cpp is preferred
because it takes an initial_prompt — restoring the glossary/vocab bias on CPU
that qwen structurally can't — and because ggml's runtime SIMD dispatch makes
one source span no-AVX2 x86 and ARM NEON (#4/#9,
docs/research/2026-06-28-stt-host-decision.md). Both CPU finals share one small
faster-whisper for live partials (`_CpuPartialsMixin`). The chooser is
`_cpu_fallback_factory`; every rung degrades, never X-or-nothing.
"""

import ctypes
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from tuparles import settings
from tuparles.config import (
    PARTIAL_WINDOW_S,
    QWEN_BINARY,
    QWEN_MODEL_DIR,
    QWEN_THREADS,
    SAMPLE_RATE,
    WHISPERCPP_MODEL,
    WHISPERCPP_THREADS,
)
from tuparles.partials import StickyLanguage, pick_language, sanitize_partial
from tuparles.preprocess import prepare_pcm, to_int16
from tuparles.transcription import (  # result types + Protocol now live in core
    Transcription,
    Word,  # noqa: F401  re-exported for back-compat (tests import it from here)
    words_from_segments,
)

# Tuned faster-whisper VAD (the D-series item, 2026-07-08 CPU review): the library
# default min_silence_duration_ms=2000 lets a 0.5-1.5s dead tail sail through, and
# a 30ms pad shears phonemes. 500ms / 200ms is tighter without clipping speech;
# capping a chunk at 30s matches Whisper's window so a long unbroken stretch still
# batches cleanly. Passed as a plain dict (faster-whisper 1.2.x builds VadOptions
# from it) so we don't couple to the VadOptions constructor. Complementary to
# trim_silence: this is in-decode VAD, trim is the upstream lead/tail cut.
TUNED_VAD_PARAMETERS = {
    "min_silence_duration_ms": 500,
    "speech_pad_ms": 200,
    "max_speech_duration_s": 30,
}


def _sticky_window_language(model, tracker, pcm):
    """One window's language for the PARTIAL path: detect once (restricted to
    the user's selected languages via `pick_language`), feed the hysteresis
    tracker, return (language_to_condition_on, detection_prob).

    Why not per-segment detection (`multilingual=True`) like the final: on a
    short/noisy partial window the detector mis-picks, and Whisper conditioned
    on the wrong language token TRANSLATES — same meaning, different words
    (translated-subtitles training data). One flaky window turned the preview
    into a translator (live report 2026-07-15). Cost: one extra encoder pass
    per partial (detect + decode) — small next to the decode itself. A failed
    detection keeps whatever the tracker already holds (never crashes a
    partial). The FINAL decode is untouched: per-segment code-switch there is
    the app's raison d'être."""
    try:
        _, _, all_probs = model.detect_language(pcm)
    except Exception:
        return tracker.language, None
    lang, prob = pick_language(all_probs, settings.get("languages") or [])
    return tracker.update(lang, prob), prob


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


def carryover_context(
    last_text: str, age_s: float, *, enabled: bool, window_s: float, max_chars: int
) -> str | None:
    """The decode context to carry from the previous take, or None (#18).

    A recent delivery's tail gives Whisper the left-context a cold-started take
    lacks — the fix for "on vient" → "rien" and for a re-dictation after a
    delete. None when disabled, stale (older than the recency window), or empty.
    Bias-only: the caller appends this to initial_prompt, which only nudges.
    """
    if not enabled or not last_text or age_s > window_s:
        return None
    return last_text[-max_chars:].strip() or None


def _compose_prompt(vocab_prompt: str | None, context: str | None) -> str | None:
    """Glossary/dict-seed prompt + carryover context at the TAIL (closest to the
    decode = strongest bias; Whisper keeps the last 224 tokens). Either may be
    None."""
    if not context:
        return vocab_prompt
    return f"{vocab_prompt} {context}" if vocab_prompt else context


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
    active_backend = "gpu"  # ambient engine indicator for the bubble/tray colour
    # large-v3-turbo handles code-switch, so the GPU preview keeps the long
    # context window. (The CPU `base` model needs a shorter one — see below.)
    partial_window_s = PARTIAL_WINDOW_S

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
        # Sticky per-take language for the partial path (translation-flip guard).
        self._partial_lang = StickyLanguage()

    def reset_partial_language(self) -> None:
        """Called by the daemon at take start: each take detects fresh."""
        self._partial_lang.reset()

    def transcribe(
        self, audio: np.ndarray, context: str | None = None
    ) -> Transcription:
        """int16 mono 16 kHz → full-quality beam decode, batched. `context` is
        the previous take's tail, carried in for onset left-context (#18)."""
        if audio.size == 0:
            return Transcription("")
        pcm = prepare_pcm(audio)
        language, multilingual = self._decode_language_opts()
        segments, info = self._batched.transcribe(
            pcm,
            batch_size=16,
            beam_size=5,
            vad_filter=True,
            vad_parameters=TUNED_VAD_PARAMETERS,
            # Re-read per decode: `tuparles vocab add` applies to the next
            # take, no restart (like the language setting). Carryover context
            # rides the tail (#18).
            initial_prompt=_compose_prompt(_vocab_prompt(), context),
            language=language,
            multilingual=multilingual,
            # Per-word confidence for the rendered-doubt span model (#23). Modest
            # alignment cost on turbo; gate via a setting if it ever bites.
            word_timestamps=True,
        )
        segs = list(segments)  # consume once: needed for both text and words
        text = " ".join(s.text.strip() for s in segs).strip()
        return Transcription(
            text,
            language=getattr(info, "language", None),
            language_prob=getattr(info, "language_probability", None),
            words=words_from_segments(segs),
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
        pcm = prepare_pcm(audio)
        language, _multilingual = self._decode_language_opts()
        if language is None:
            # 0 or 2+ selected languages: NEVER per-segment detection here —
            # one mis-picked window flips the preview into translator mode.
            # Sticky + hysteresis instead; None until a confident detection
            # (in-decode detection then, no wrong-token bias).
            language, _ = _sticky_window_language(self._model, self._partial_lang, pcm)
        segments, _ = self._model.transcribe(
            pcm,
            beam_size=1,
            vad_filter=True,
            vad_parameters=TUNED_VAD_PARAMETERS,
            condition_on_previous_text=False,
            without_timestamps=True,
            language=language,
            multilingual=False,
        )
        return sanitize_partial(segments)


class CpuPartialsEngine:
    """A small whisper on CPU, for live *partials only* (#127). The qwen final
    decode stays the source of truth; this just paints provisional text while
    you speak, so CPU sessions get the streaming preview the GPU has — partials
    degrade GPU-or-CPU like every other feature, never GPU-or-nothing.

    Cheap by construction: faster-whisper is already a core dep and its CT2 CPU
    backend needs no CUDA, so this rides the lean install — only the small model
    weights fetch on first use (like the GPU model). A bounded window + greedy
    beam keep a re-decode well above realtime (`base` ≈ 0.6 s for an 8 s window
    on a laptop CPU), and the daemon's ~1 Hz loop self-paces, so a long window
    just yields fewer partials, never a backlog. Default `base`; drop to `tiny`
    on a low-power box via the `cpu_partials_model` setting.

    Partials ≠ final: this is a different (smaller) model than qwen, so the
    preview can drift slightly from what lands. That's the deal with every
    partial — provisional text the final decode overwrites.
    """

    def __init__(self, model: str | None = None) -> None:
        from faster_whisper import WhisperModel

        name = model or settings.get("cpu_partials_model") or "base"
        self._model = WhisperModel(name, device="cpu", compute_type="int8")
        # Last language this model detected on a partial — the qwen final decode
        # emits no language (it runs --silent), so on CPU this is the only
        # code-switch signal we have. It's the *partials* model's guess, not
        # qwen's, so a signal not ground truth; the final engine reads it (#10).
        self.last_language: str | None = None
        self.last_language_prob: float | None = None
        # Sticky per-take language for the partial path (translation-flip guard).
        self._partial_lang = StickyLanguage()

    def reset_partial_language(self) -> None:
        self._partial_lang.reset()

    def transcribe_partial(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
        pcm = prepare_pcm(audio)
        language, _multilingual = decode_language_opts(settings.get("languages") or [])
        prob: float | None = None
        if language is None:
            # Same translation-flip guard as the GPU partial path (see
            # _sticky_window_language) — the small model mis-picks even more.
            language, prob = _sticky_window_language(
                self._model, self._partial_lang, pcm
            )
        segments, info = self._model.transcribe(
            pcm,
            beam_size=1,
            vad_filter=True,
            vad_parameters=TUNED_VAD_PARAMETERS,
            condition_on_previous_text=False,
            without_timestamps=True,
            language=language,
            multilingual=False,
        )
        if language is not None:
            # Conditioned decode: info.language just echoes the token — keep
            # the sticky language + the DETECTION's own confidence instead.
            self.last_language, self.last_language_prob = language, prob
        else:
            self.last_language = getattr(info, "language", None)
            self.last_language_prob = getattr(info, "language_probability", None)
        return sanitize_partial(segments)


class _CpuPartialsMixin:
    """Live-partials behaviour shared by every CPU *final* engine (qwen, whisper.cpp).

    The final CPU engines can't cheaply stream their own preview (qwen is a fresh
    process per utterance; whisper.cpp streaming is broken on CPU — Android #4),
    so both paint the live bubble from one small faster-whisper (`CpuPartialsEngine`,
    #127), built lazily on the first partial and opt-out via `cpu_partials_enabled`.
    If it can't load (e.g. no network on first use), partials degrade silently to a
    waveform-only bubble rather than crashing a take. Sharing this is the whole
    reason both CPU rungs feel identical while you speak; only the final decode
    differs. The mixin also exposes `self._partials` so a final engine can borrow
    the small model's last language detection as its code-switch signal (#10)."""

    active_backend = "cpu"

    def __init__(self, partials_factory=CpuPartialsEngine) -> None:
        self._partials_factory = partials_factory
        self._partials: CpuPartialsEngine | None = None  # built lazily
        self._partials_failed = False  # small model couldn't load → waveform-only

    @property
    def supports_partials(self) -> bool:
        """Opt-in (default on): the extra small model is worth it for the live
        preview, but a low-power box can turn it off. Optimistic — if enabled
        but the model later fails to load, `transcribe_partial` degrades to ''
        (waveform-only) rather than crashing a take."""
        return bool(settings.get("cpu_partials_enabled"))

    @property
    def partial_window_s(self) -> int:
        """Short tail (default 6 s) so the `base` model's one-language-per-window
        detection tracks the *current* language instead of a French-dominant past
        (#3 follow-up). Hot-reloaded — retune without a restart."""
        return int(settings.get("cpu_partials_window_s") or PARTIAL_WINDOW_S)

    def reset_partial_language(self) -> None:
        # Best-effort: the small model builds lazily; before it exists there
        # is no sticky state to clear.
        if self._partials is not None:
            self._partials.reset_partial_language()

    def transcribe_partial(self, audio: np.ndarray) -> str:
        if self._partials_failed or not settings.get("cpu_partials_enabled"):
            return ""
        if self._partials is None:
            try:
                self._partials = self._partials_factory()
            except Exception as exc:
                print(
                    f"CPU partials model unavailable ({str(exc)[:120]}); waveform-only"
                )
                self._partials_failed = True
                return ""
        return self._partials.transcribe_partial(audio)


class QwenCpuEngine(_CpuPartialsMixin):
    """Fallback: vendored qwen-asr C binary, fresh process per utterance
    (weights are mmap'd, spawn costs ~0.65 s). Live partials come from the shared
    `_CpuPartialsMixin` (a small faster-whisper, #127). qwen takes no prompt, so it
    can't be vocab-biased — the reason whisper.cpp (#4) exists as the other CPU
    rung: same partials, but a promptable final decode that restores glossary bias.
    """

    def transcribe(
        self, audio: np.ndarray, context: str | None = None
    ) -> Transcription:
        # context is GPU-only (the qwen binary takes no prompt); accepted for a
        # uniform engine interface, ignored here (#18).
        if audio.size == 0:
            return Transcription("")
        # Close the temp file before writing/reading it by name: Windows forbids
        # reopening a temp file whose handle is still open (PermissionError), so
        # mkstemp + close the fd, then write the WAV and hand the path to qwen,
        # and clean up by hand. Identical behaviour on Linux/macOS.
        fd, tmp_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            # Route qwen through the shared decode-prep too (#131): it used to
            # write the raw int16 buffer — the one engine that bypassed
            # normalization. Normalize on CPU, then back to int16 for the WAV the
            # C binary reads, so every rung conditions audio identically now.
            _write_wav(tmp_path, to_int16(prepare_pcm(audio)))
            result = subprocess.run(
                [
                    str(QWEN_BINARY),
                    "-d",
                    str(QWEN_MODEL_DIR),
                    "-i",
                    str(tmp_path),
                    "-t",
                    str(QWEN_THREADS),
                    "--silent",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"qwen_asr failed: {result.stderr.strip()[:500]}")
        # qwen emits no language, so borrow the partials model's last detection
        # as the take's code-switch signal (None when partials are off). Honest
        # about provenance: it's the small model's guess, not qwen's (#10).
        return Transcription(
            result.stdout.strip(),
            language=getattr(self._partials, "last_language", None),
            language_prob=getattr(self._partials, "last_language_prob", None),
        )


def _default_whispercpp_model(name: str):
    """Build the real whisper.cpp model (pywhispercpp). Isolated so the engine's
    decode logic is testable with a fake factory — and so the heavy, optional
    native import is lazy: it lives in the `whispercpp` poetry group, absent from
    the lean/GPU install, and only fires the moment this rung is actually chosen
    (load_engine catches the ImportError and falls back to qwen)."""
    from pywhispercpp.model import Model

    # n_threads at construction so every decode reuses it; logs muted (ggml is
    # chatty at load). `name` resolves a ggml weight by name (fetched + cached)
    # or an absolute path to a .bin.
    return Model(
        name,
        n_threads=WHISPERCPP_THREADS,
        print_realtime=False,
        print_progress=False,
        redirect_whispercpp_logs_to=None,
    )


class WhisperCppEngine(_CpuPartialsMixin):
    """The promptable CPU rung (#4): whisper.cpp via pywhispercpp.

    Why it exists *alongside* qwen, sharing the same partials: qwen takes no
    prompt, so the personal glossary + carryover context can't bias its decode
    (the documented "pipeline" → "payplane" fumble). whisper.cpp honours
    `initial_prompt`, so this rung restores on CPU exactly the vocab bias the GPU
    path has — same small-model live preview (`_CpuPartialsMixin`), a *promptable*
    final decode. It is also the portable engine: ggml does runtime SIMD dispatch,
    so the one source runs on no-AVX2 x86 AND ARM NEON where qwen's -march=native
    build can't (#9) — the reason it's the public CPU-rung host on the Pi 5
    (docs/research/2026-06-28-stt-host-decision.md).

    Optional + lazy: pywhispercpp lives in the `whispercpp` poetry group, so the
    lean/GPU install never pays for the native build. `load_engine()` prefers this
    over qwen only when it imports AND a model loads; otherwise qwen — GPU-or-CPU,
    never GPU-or-nothing, all the way down the gradient. The whisper.cpp model is
    injectable (`model_factory`) so the prompt/language logic is tested without the
    native lib; the real WER-vs-qwen bar is measured on real hardware (#5b/#19),
    not asserted here.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        model_factory=None,
        partials_factory=CpuPartialsEngine,
    ) -> None:
        super().__init__(partials_factory=partials_factory)
        name = model or settings.get("whispercpp_model") or WHISPERCPP_MODEL
        # Resolve the real factory at call time (module global, not a frozen
        # default) so a test can inject a fake and the chooser path is patchable.
        self._model = (model_factory or _default_whispercpp_model)(name)

    def transcribe(
        self, audio: np.ndarray, context: str | None = None
    ) -> Transcription:
        """Promptable final decode — the whole reason this rung exists. The
        glossary/dict-seed prompt + the previous take's carryover context ride
        `initial_prompt` (#68/#18), exactly like the GPU path; that's the bias
        qwen structurally can't take."""
        if audio.size == 0:
            return Transcription("")
        pcm = prepare_pcm(audio)
        language, _multilingual = decode_language_opts(settings.get("languages") or [])
        # whisper.cpp has no per-segment `multilingual` flag (that's a
        # faster-whisper extension), so we can't follow a mid-sentence switch the
        # way the GPU does. "auto" lets it detect per decode (the best this binding
        # offers); a single forced language still pins when the user picked exactly
        # one. Honest limitation — the GPU rung remains the code-switch ceiling.
        segments = self._model.transcribe(
            pcm,
            language=language or "auto",
            initial_prompt=_compose_prompt(_vocab_prompt(), context) or "",
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        # Borrow the partials model's last detection as the code-switch signal,
        # same as qwen (#10) — honest about provenance (the small preview model's
        # guess, not the final decode's). whisper.cpp can report its own detected
        # language, but the binding's surface for it varies across versions; revisit
        # if the per-decode language proves worth the version-coupling.
        return Transcription(
            text,
            language=getattr(self._partials, "last_language", None),
            language_prob=getattr(self._partials, "last_language_prob", None),
        )


def _cpu_fallback_factory():
    """The CPU rung chooser: prefer the promptable whisper.cpp engine when it's
    installed AND a model loads, else qwen. Restores glossary bias on CPU where
    available, degrades to qwen where not — never X-or-nothing. Lazy by design:
    the pywhispercpp import only fires here, when the CPU rung is actually built
    (GPU dead or absent), so the GPU/lean path never imports the native lib."""
    try:
        return WhisperCppEngine()
    except Exception as exc:
        print(f"whisper.cpp CPU rung unavailable ({str(exc)[:120]}); qwen-asr CPU")
        return QwenCpuEngine()


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

    def __init__(
        self, gpu_factory=GpuEngine, cpu_factory=_cpu_fallback_factory
    ) -> None:
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
    def active_backend(self) -> str:
        """ "gpu" | "cpu" — which silicon is live. Drives the bubble/tray colour
        (green=GPU, blue=CPU). The fallback is sticky for the session, so this
        flips to "cpu" exactly when the GPU has truly given up and stays there."""
        return "cpu" if self._on_cpu else "gpu"

    @property
    def supports_partials(self) -> bool:
        # On GPU: whenever a live context exists. After a sticky fallback: defer
        # to the CPU engine, which now streams via its own small model (#127).
        if self._on_cpu:
            return self._cpu_engine().supports_partials
        return self._gpu is not None

    @property
    def partial_window_s(self) -> int:
        # The CPU backend wants a shorter window than the GPU (code-switch language
        # tracking, #3 follow-up). Follow the live backend so the daemon's tail
        # length always matches whichever silicon is decoding.
        if self._on_cpu:
            return self._cpu_engine().partial_window_s
        return PARTIAL_WINDOW_S

    def transcribe(
        self, audio: np.ndarray, context: str | None = None
    ) -> Transcription:
        if self._on_cpu:
            return self._cpu_engine().transcribe(audio, context)
        try:
            return self._gpu.transcribe(audio, context)
        except Exception as exc:
            print(f"GPU decode failed ({str(exc)[:120]}); rebuilding CUDA context")
            if self._rebuild_gpu():
                try:
                    return self._gpu.transcribe(audio, context)
                except Exception as exc2:
                    print(f"GPU still failing ({str(exc2)[:120]}); CPU fallback")
            self._on_cpu = True
            return self._cpu_engine().transcribe(audio, context)

    def reset_partial_language(self) -> None:
        # Follow the live backend, like transcribe_partial. Best-effort: a
        # missing hook (or a dead GPU) just means no sticky state to clear.
        try:
            target = self._cpu_engine() if self._on_cpu else self._gpu
            reset = getattr(target, "reset_partial_language", None)
            if callable(reset):
                reset()
        except Exception:
            pass

    def transcribe_partial(self, audio: np.ndarray) -> str:
        # Partials are frequent and best-effort: never rebuild on one (it would
        # thrash), never fall back — let the final transcribe() drive recovery.
        # After a sticky CPU fallback, partials come from the CPU engine's own
        # small model (#127); before that, from the live GPU context.
        try:
            if self._on_cpu:
                return self._cpu_engine().transcribe_partial(audio)
            if self._gpu is None:
                return ""
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
    at startup, and never get stuck with no STT after a suspend/resume. The CPU
    rung is whisper.cpp when installed (promptable, portable), else qwen —
    chosen by `_cpu_fallback_factory`, here and inside ResilientEngine."""
    try:
        return ResilientEngine()
    except Exception as exc:
        print(f"GPU engine unavailable ({exc}); falling back to CPU rung")
        return _cpu_fallback_factory()


def _write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio.astype(np.int16).tobytes())
