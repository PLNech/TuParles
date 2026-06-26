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

from tuparles.config import (
    PARTIAL_AVG_LOGPROB_MIN,
    PARTIAL_COMPRESSION_MAX,
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
