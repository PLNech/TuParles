"""Sanity-filtering for live partials (#3).

A partial is a *provisional* preview the final decode overwrites, so the only
honest cleanup is to SUPPRESS what the decoder itself flags as junk - never to
rewrite words (a wrong autocorrect is worse than a visible mishear). We drop a
segment only on faster-whisper's own confidence signals ("this isn't speech",
"this is a repetition loop") plus a short denylist of the canonical Whisper
hallucination phrases - the YouTube-caption ghosts it emits on silence/noise.

What this deliberately does NOT catch: a *confident mishear* of real speech
("ta courte vie" for something else). Distinguishing that from a correct decode
means judging meaning, which we refuse. It still flashes; the final decode is
the truth and overwrites it. The bias is asymmetric: err toward *showing* a
rough partial over blanking the bubble (the live preview is the point).

Pure and engine-agnostic so the GPU and CPU partial paths share one contract
(can't diverge, like `pipeline.postprocess`) and it's unit-testable headless -
the GPU path can't be exercised when the card is wedged, but the logic still
gets covered. Engines pass faster-whisper Segment objects; we read fields
defensively so a plain test namedtuple works too.
"""

from tuparles.config_core import (
    PARTIAL_AVG_LOGPROB_MIN,
    PARTIAL_COMPRESSION_MAX,
    PARTIAL_LANG_CONFIDENCE,
    PARTIAL_LANG_STABLE_WINDOWS,
    PARTIAL_NO_SPEECH_MAX,
)

# Canonical Whisper hallucination phrases, in *normalized* form (see _normalize:
# lower-cased, punctuation stripped, whitespace collapsed). Matched against the
# WHOLE segment only - never as a substring - so "merci beaucoup pour ton aide"
# survives even though bare "merci ..." caption-spam is listed. Keep this short
# and unambiguous: the confidence gates do the heavy lifting; this is a backstop
# for the few phrases Whisper emits *confidently* on silence.
_HALLUCINATION_PHRASES = frozenset(
    {
        # FR caption ghosts
        "sous titres realises par la communaute damaraorg",
        "sous titres realises par lassociation des paralyses de france",
        "merci davoir regarde cette video",
        "merci de votre attention",
        "merci a tous",
        # EN caption ghosts
        "thanks for watching",
        "thank you for watching",
        "please subscribe",
        "like and subscribe",
        "subtitles by the amaraorg community",
        "amaraorg",
    }
)


def _normalize(text: str) -> str:
    """Lower-case, drop punctuation, collapse whitespace - so denylist matching
    is robust to the trailing dot / casing Whisper sprinkles on its ghosts."""
    kept = [c for c in text.lower() if c.isalnum() or c.isspace()]
    return " ".join("".join(kept).split())


def _field(seg, name: str, default: float) -> float:
    """Read a Segment confidence field defensively (missing → default = keep)."""
    value = getattr(seg, name, default)
    return default if value is None else float(value)


def _is_sound_tag(text: str) -> bool:
    """A whole segment wrapped in brackets/note-marks is a Whisper non-speech
    tag ("[Music]", "(applause)", "♪…♪"), not something the user said."""
    return bool(text) and text[0] in "[({♪" and text[-1] in "])}♪"


def _keep(seg) -> bool:
    """Structural gates only, no meaning-judging. Default to keeping."""
    text = (getattr(seg, "text", "") or "").strip()
    if _is_sound_tag(text):
        return False
    norm = _normalize(text)
    if not norm:  # pure punctuation / note marks ("...", "♪") → nothing said
        return False
    if norm in _HALLUCINATION_PHRASES:
        return False
    # Whisper's own no-speech test: only the *combination* of a high no-speech
    # probability AND a low average logprob means "this is silence" - either
    # alone is too trigger-happy and would blank rough-but-real speech.
    if (
        _field(seg, "no_speech_prob", 0.0) > PARTIAL_NO_SPEECH_MAX
        and _field(seg, "avg_logprob", 0.0) < PARTIAL_AVG_LOGPROB_MIN
    ):
        return False
    # Degenerate repetition loop ("ok ok ok ok …") compresses absurdly well.
    return _field(seg, "compression_ratio", 0.0) <= PARTIAL_COMPRESSION_MAX


def sanitize_partial(segments) -> str:
    """faster-whisper segments → preview text with decoder-flagged junk dropped.

    Survivors are joined as-is: we suppress whole segments, never edit words.
    """
    return " ".join(seg.text.strip() for seg in segments if _keep(seg)).strip()


# --- sticky partial language (2026-07-15) ------------------------------------
# With 2+ selected languages the partial path let faster-whisper re-detect the
# language per segment, and ONE short/noisy window mis-picking flips Whisper
# into genuine TRANSLATION — same meaning, different words (the model saw a lot
# of translated subtitles). The tracker below makes the per-window language
# sticky with hysteresis: switch only on PARTIAL_LANG_STABLE_WINDOWS
# consecutive confident (≥ PARTIAL_LANG_CONFIDENCE) detections of the same
# other language. Deliberate mid-take switches still land (two windows ≈ one
# spoken sentence); a single flaky window no longer turns translator. Pure and
# engine-agnostic, like sanitize_partial: the GPU and CPU partial paths share
# one contract, and the logic is testable with no model. The FINAL decode is
# untouched — per-segment code-switching there is the app's raison d'être.


def pick_language(
    all_probs: "list[tuple[str, float]] | None", allowed: "list[str]"
) -> "tuple[str | None, float]":
    """The most probable language RESTRICTED to the user's selection.

    `all_probs` is faster-whisper's `detect_language` third return (every
    language with its probability). With a non-empty `allowed`, only those
    candidates compete — the user said "I speak en+fr", so a spurious 0.4 "nl"
    can never win. Probabilities are NOT renormalized: the confidence gate
    reads the raw mass so a window that is genuinely ambiguous (0.3 en / 0.3
    fr) stays below the floor instead of being inflated to a fake certainty.
    Empty/None input → (None, 0.0)."""
    if not all_probs:
        return None, 0.0
    pool = [(lang, p) for lang, p in all_probs if lang in allowed] if allowed else None
    if not pool:  # no restriction, or nothing of the selection detected at all
        pool = list(all_probs)
    lang, prob = max(pool, key=lambda lp: lp[1])
    return lang, float(prob)


class StickyLanguage:
    """Per-take language tracker with hysteresis for the partial path.

    update() feeds one window's (detected, prob) and returns the language to
    CONDITION the window's decode on — or None while nothing confident has
    been seen yet (the caller then passes language=None: in-decode detection,
    no wrong-token bias). First confident window locks immediately (nothing to
    be sticky from); after that a switch needs `stable` CONSECUTIVE confident
    windows of the same other language — an unconfident window breaks the
    streak. reset() at take start: each take detects fresh."""

    def __init__(
        self,
        confidence: float = PARTIAL_LANG_CONFIDENCE,
        stable: int = PARTIAL_LANG_STABLE_WINDOWS,
    ) -> None:
        self._confidence = confidence
        self._stable = stable
        self.reset()

    def reset(self) -> None:
        self._lang: str | None = None
        self._candidate: str | None = None
        self._streak = 0

    @property
    def language(self) -> "str | None":
        return self._lang

    def update(self, detected: "str | None", prob: "float | None") -> "str | None":
        if detected is None or prob is None or prob < self._confidence:
            # Unconfident window: no switch progress (consecutive means
            # consecutive), and never lock onto a low-confidence token.
            self._candidate, self._streak = None, 0
            return self._lang
        if self._lang is None:  # first confident window of the take
            self._lang = detected
            return self._lang
        if detected == self._lang:
            self._candidate, self._streak = None, 0
            return self._lang
        if detected == self._candidate:
            self._streak += 1
        else:
            self._candidate, self._streak = detected, 1
        if self._streak >= self._stable:
            self._lang, self._candidate, self._streak = detected, None, 0
        return self._lang
