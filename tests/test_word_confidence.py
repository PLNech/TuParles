"""Per-word confidence extraction (#23) — pure, headless. The GPU decode can't
run with no card, but words_from_segments is engine-agnostic (reads fields
defensively), so the logic that feeds rendered-doubt still gets covered."""

from collections import namedtuple

from tuparles.engine import Transcription, Word, words_from_segments

_W = namedtuple("FakeWord", ["word", "probability", "start", "end"])
_Seg = namedtuple("FakeSeg", ["text", "words"])


def test_flattens_words_across_segments():
    segs = [
        _Seg("on vient", [_W("on", 0.41, 0.0, 0.2), _W(" vient", 0.95, 0.2, 0.5)]),
        _Seg(" d'avoir", [_W(" d'avoir", 0.88, 0.5, 0.8)]),
    ]
    words = words_from_segments(segs)
    assert [w.text for w in words] == ["on", " vient", " d'avoir"]
    assert words[0].probability == 0.41  # the uncertain onset, preserved
    assert words[1].start == 0.2


def test_segments_without_words_yield_empty():
    # word_timestamps was off → no .words → empty list, not an error
    NoWords = namedtuple("NoWords", ["text", "words"])
    assert words_from_segments([NoWords("hi", None)]) == []


def test_missing_probability_defaults_certain():
    seg = _Seg("x", [_W("x", None, 0.0, 0.1)])
    assert words_from_segments([seg])[0].probability == 1.0


def test_transcription_words_default_none():
    # engines that don't expose words (qwen --silent) leave it None
    assert Transcription("bonjour").words is None


def test_word_is_a_dataclass_with_confidence():
    w = Word("test", 0.5)
    assert w.text == "test" and w.probability == 0.5 and w.start is None
