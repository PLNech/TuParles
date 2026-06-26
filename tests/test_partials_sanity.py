"""#3 — live-partials sanity filter: SUPPRESS decoder-flagged junk, never rewrite.

Pure-function tests with fake faster-whisper segments, so the contract is
covered headless (the GPU partial path can't run with the card wedged). The
guiding bias is asymmetric: drop only what the decoder itself flags as junk,
and when in doubt KEEP — a rough partial beats a blank bubble.
"""

from collections import namedtuple

from tuparles.partials import sanitize_partial

# Mirrors the fields the filter reads off a faster-whisper Segment.
Seg = namedtuple("Seg", "text avg_logprob no_speech_prob compression_ratio")


def good(text):
    """A confident, speech-like segment — the common case, always kept."""
    return Seg(text, avg_logprob=-0.3, no_speech_prob=0.02, compression_ratio=1.3)


def test_good_speech_is_kept():
    assert sanitize_partial([good("bonjour le monde")]) == "bonjour le monde"


def test_silence_hallucination_is_dropped():
    # High no_speech_prob AND low logprob together = Whisper's own "no speech".
    junk = Seg("Merci.", avg_logprob=-1.4, no_speech_prob=0.85, compression_ratio=0.9)
    assert sanitize_partial([junk]) == ""


def test_no_speech_alone_does_not_drop():
    # High no_speech_prob but a confident logprob → KEEP. Either signal alone is
    # too trigger-happy; only the combination means silence. Guards the praised
    # live preview against over-suppression.
    seg = Seg(
        "c'est bien ça", avg_logprob=-0.4, no_speech_prob=0.8, compression_ratio=1.2
    )
    assert sanitize_partial([seg]) == "c'est bien ça"


def test_low_logprob_alone_does_not_drop():
    # A rough-but-real mishear comes back with a low logprob and low no_speech.
    # We do NOT drop it — that's the boundary: suppress flagged junk, show
    # uncertain speech (the final decode is the truth).
    seg = Seg(
        "ta courte vie", avg_logprob=-1.5, no_speech_prob=0.1, compression_ratio=1.1
    )
    assert sanitize_partial([seg]) == "ta courte vie"


def test_repetition_loop_is_dropped():
    loop = Seg(
        "ok ok ok ok ok ok", avg_logprob=-0.2, no_speech_prob=0.1, compression_ratio=3.1
    )
    assert sanitize_partial([loop]) == ""


def test_canonical_caption_phrase_is_dropped_even_when_confident():
    # Whisper emits these *confidently*, so no confidence gate catches them —
    # the exact-phrase denylist is the backstop. Trailing dot / casing tolerated.
    seg = Seg(
        "Thanks for watching.",
        avg_logprob=-0.1,
        no_speech_prob=0.05,
        compression_ratio=1.0,
    )
    assert sanitize_partial([seg]) == ""


def test_bare_merci_is_kept():
    # Bare "merci" is a real word, not denylisted — only the multi-word caption
    # phrases are. Conservative: we never ban a legitimate utterance.
    assert sanitize_partial([good("merci")]) == "merci"


def test_denylist_is_whole_segment_not_substring():
    # "thanks for watching" is denylisted, but a real sentence containing it must
    # survive — matching is on the whole normalized segment, never a substring.
    seg = good("thanks for watching my back today")
    assert sanitize_partial([seg]) == "thanks for watching my back today"


def test_pure_music_or_punctuation_is_dropped():
    for noise in ("♪♪♪", "...", "[Music]"):
        seg = good(noise)
        assert sanitize_partial([seg]) == "", noise


def test_mixed_keeps_good_drops_junk():
    segs = [
        good("on commence la réunion"),
        Seg("Merci.", avg_logprob=-1.5, no_speech_prob=0.9, compression_ratio=0.8),
        good("et voilà"),
    ]
    assert sanitize_partial(segs) == "on commence la réunion et voilà"


def test_empty_segments_yield_empty():
    assert sanitize_partial([]) == ""


def test_missing_confidence_fields_default_to_keep():
    # A segment exposing only .text (defensive read) is kept, not crashed on.
    Bare = namedtuple("Bare", "text")
    assert sanitize_partial([Bare("hello there")]) == "hello there"
