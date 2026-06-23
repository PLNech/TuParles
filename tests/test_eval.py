"""Unit tests for the eval scorer — pure logic, no GPU, no audio.

The scorer is the gate the whole code-switch suite trusts; if it lies, every
verdict downstream lies. So we pin its corners here before any WAV exists.
"""

import json
from pathlib import Path

from tuparles.eval import (
    contains_phrase,
    normalize,
    score_case,
    tokens,
    wer,
)

CORPUS = Path(__file__).parent / "data" / "codeswitch" / "corpus.json"


def test_normalize_folds_case_accents_and_seams():
    # apostrophes and hyphens become spaces; case folds; NFC.
    assert normalize("Fan-Out") == "fan out"
    assert normalize("c'est") == "c est"
    assert normalize("  Deux   points… ") == "deux points"


def test_contains_phrase_is_contiguous_tokens_not_substring():
    hay = tokens("le fan outil est cassé")  # ['le','fan','outil','est','casse']
    # 'fan out' must NOT match inside 'fan outil' (substring would have)
    assert not contains_phrase(hay, tokens("fan out"))
    assert contains_phrase(tokens("on va fan out les agents"), tokens("fan out"))


def test_contains_phrase_empty_needle_is_true():
    assert contains_phrase(tokens("whatever"), [])


def test_wer_basic():
    assert wer("a b c", "a b c") == 0.0
    assert wer("a b c", "a x c") == 1 / 3
    assert wer("", "") == 0.0
    assert wer("", "noise") == 1.0
    # insertions can exceed 1.0 — a hallucinated tail is worse than a deletion
    assert wer("a", "a b c d") == 3.0


def test_score_case_pass():
    case = {
        "id": "ok",
        "text": "il faut ship la feature",
        "must_contain": ["ship", "feature"],
        "must_not_contain": ["chip"],
    }
    r = score_case(case, "Il faut ship la feature.")
    assert r.passed and not r.missing and not r.leaked
    assert r.wer == 0.0


def test_score_case_missing_slot_fails():
    case = {
        "id": "miss",
        "text": "ship it",
        "must_contain": ["ship it"],
        "must_not_contain": [],
    }
    r = score_case(case, "chip it maintenant")
    assert not r.passed
    assert r.missing == ["ship it"]


def test_score_case_leaked_misfire_fails():
    case = {
        "id": "leak",
        "text": "fan out les agents",
        "must_contain": ["fan out"],
        "must_not_contain": ["fais un air"],
    }
    r = score_case(case, "tu fais un air de jamais les agents")
    assert not r.passed
    assert "fan out" in r.missing
    assert "fais un air" in r.leaked


def test_summary_is_readable():
    case = {"id": "x", "text": "a", "must_contain": ["a"], "must_not_contain": []}
    assert score_case(case, "a").summary().startswith("PASS x")


# --- corpus integrity (the dataset itself is an artifact under test) --------


def test_corpus_loads_and_is_well_formed():
    corpus = json.loads(CORPUS.read_text())
    ids = [c["id"] for c in corpus["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    assert len(ids) >= 15, "corpus shrank unexpectedly"
    for c in corpus["cases"]:
        assert c["text"].strip(), f"{c['id']}: empty text"
        assert c["must_contain"], f"{c['id']}: a case must assert at least one slot"
        # every must_contain phrase must actually be present in its own
        # reference text — else the case can never pass even on a perfect decode
        hay = tokens(c["text"])
        for phrase in c["must_contain"]:
            assert contains_phrase(hay, tokens(phrase)), (
                f"{c['id']}: must_contain '{phrase}' absent from reference text"
            )


def test_corpus_misfires_are_absent_from_reference():
    # a must_not_contain that appears in the reference text is a bug in the case
    corpus = json.loads(CORPUS.read_text())
    for c in corpus["cases"]:
        hay = tokens(c["text"])
        for phrase in c.get("must_not_contain", []):
            assert not contains_phrase(hay, tokens(phrase)), (
                f"{c['id']}: must_not_contain '{phrase}' is in the reference text"
            )
