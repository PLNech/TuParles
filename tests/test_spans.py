"""The Span token-stream model (#21). The load-bearing guarantee is the
round-trip invariant — `flatten(tokenize(t)) == t` byte for byte — pinned against
the real code-switch corpus, so the span layer can never become a lossy second
source of truth. Pure + headless."""

import json
from pathlib import Path

import pytest

from tuparles.spans import Span, flatten, tokenize

_CORPUS = Path(__file__).parent / "data" / "codeswitch" / "corpus.json"
_TEXTS = [c["text"] for c in json.loads(_CORPUS.read_text(encoding="utf-8"))["cases"]]


class TestRoundTrip:
    """flatten ∘ tokenize is the identity — the invariant everything rests on."""

    @pytest.mark.parametrize("text", _TEXTS)
    def test_corpus_round_trips_byte_for_byte(self, text):
        assert flatten(tokenize(text)) == text

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "\n",
            "a\n\nb",
            "l'autre c'est-à-dire",  # apostrophes + hyphens
            "café déjà où",  # accents are word chars
            "fan out, ship it!",
            "deux  espaces\tet\tune tab",
            "ponctuation??!… «guillemets»",
            "trailing space ",
            " leading",
            "中文 mixed with english",  # non-latin word chars
        ],
    )
    def test_edge_cases_round_trip(self, text):
        assert flatten(tokenize(text)) == text


class TestTokenKinds:
    def test_splits_into_expected_kinds(self):
        spans = tokenize("ship it!\nok")
        assert [(s.text, s.kind) for s in spans] == [
            ("ship", "word"),
            (" ", "space"),
            ("it", "word"),
            ("!", "punct"),
            ("\n", "newline"),
            ("ok", "word"),
        ]

    def test_accented_and_underscore_are_words(self):
        assert [s.kind for s in tokenize("déjà_vu")] == ["word"]

    def test_runs_of_punct_and_space_stay_together(self):
        spans = tokenize("a??  b")
        assert [(s.text, s.kind) for s in spans] == [
            ("a", "word"),
            ("??", "punct"),
            ("  ", "space"),
            ("b", "word"),
        ]

    def test_empty_is_no_spans(self):
        assert tokenize("") == []


class TestConfidence:
    def test_default_decoded_is_certain(self):
        for s in tokenize("bonjour le monde"):
            assert s.certain
            assert s.origin == "decoded"

    def test_word_confidence_applies_to_words_only(self):
        spans = tokenize("ship it!", confidence=0.4)
        by_kind = {s.kind: s for s in spans}
        assert by_kind["word"].confidence == 0.4
        assert not by_kind["word"].certain
        assert by_kind["punct"].confidence is None  # marks/space stay certain
        assert by_kind["punct"].certain

    def test_confidence_one_is_certain(self):
        assert Span("x", "word", confidence=1.0).certain
        assert Span("x", "word", confidence=None).certain
        assert not Span("x", "word", confidence=0.5).certain


class TestRewritten:
    def test_original_none_means_untouched(self):
        assert not Span("Claude", "word").rewritten

    def test_differing_original_is_a_rewrite(self):
        s = Span("Claude", "word", origin="rewritten", original="cloud")
        assert s.rewritten

    def test_same_original_is_not_a_rewrite(self):
        # re-cased to the same surface, say — original set but equal ⇒ not a change
        assert not Span("ok", "word", origin="cased", original="ok").rewritten
