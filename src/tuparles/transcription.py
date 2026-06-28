"""The transcription contract: result types + the engine Protocol.

This is the public surface a frontend consumes — what a decode returns, and what
any engine must expose — lifted into the portable core (extraction step 4) so
every frontend (desktop GUI, headless service, HTTP server, Android) shares one
definition instead of re-deriving it. Concrete engines live in their frontend:
faster-whisper/CUDA + the qwen subprocess on desktop, whisper.cpp via JNI on
Android. They depend on THIS; nothing here depends on them.

Stdlib-only at runtime — numpy appears only in type hints under TYPE_CHECKING —
so it imports with no engine/GPU/desktop deps present (see
tests/test_core_boundary.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


@dataclass
class Word:
    """One decoded word + the model's confidence in it (#23). `probability` is
    faster-whisper's per-word score in [0, 1]; lower = the model was less sure.
    Feeds the rendered-doubt span model (#16/#24) — we show the uncertainty,
    never silently rewrite it."""

    text: str
    probability: float
    start: float | None = None
    end: float | None = None


@dataclass
class Transcription:
    """Final-decode result: text + the metadata engines used to discard."""

    text: str
    language: str | None = None
    language_prob: float | None = None
    # Per-word confidence when the engine exposes it (GPU/faster-whisper with
    # word_timestamps); None on engines that don't (qwen runs --silent). The
    # doubt UI degrades to no-dimming when absent — GPU-or-CPU, never GPU-or-nothing.
    words: list[Word] | None = None


def words_from_segments(segments) -> list[Word]:
    """faster-whisper segments → flat [Word]. Reads fields defensively so a
    plain test namedtuple works, and skips segments without word timings (the
    list is empty, not an error, when word_timestamps was off). Pure + headless-
    testable, like `sanitize_partial` — the GPU path can't run with no card."""
    words: list[Word] = []
    for seg in segments:
        for w in getattr(seg, "words", None) or []:
            text = getattr(w, "word", None)
            if text is None:
                continue
            prob = getattr(w, "probability", None)
            words.append(
                Word(
                    text=text,
                    probability=1.0 if prob is None else float(prob),
                    start=getattr(w, "start", None),
                    end=getattr(w, "end", None),
                )
            )
    return words


@runtime_checkable
class TranscriptionEngine(Protocol):
    """What every engine exposes, GPU or CPU. Frontends depend on this Protocol,
    not on a concrete engine class — so the gradient (CUDA → qwen → whisper.cpp)
    can swap the implementation without touching a caller. Honouring the house
    doctrine, callers degrade gracefully: `supports_partials` may be False and
    `Transcription.words` may be None."""

    #: Ambient backend indicator for the bubble/tray colour ("gpu" | "cpu").
    active_backend: str
    #: Whether the engine can produce live partials.
    supports_partials: bool
    #: Seconds of tail the partial decode looks at.
    partial_window_s: int

    def transcribe(
        self, audio: np.ndarray, context: str | None = None
    ) -> Transcription:
        """Final decode: mono 16 kHz audio → Transcription. `context` is the
        previous take's tail, carried in for onset left-context (#18)."""
        ...

    def transcribe_partial(self, audio: np.ndarray) -> str:
        """Fast provisional decode of the growing buffer for the live preview."""
        ...
