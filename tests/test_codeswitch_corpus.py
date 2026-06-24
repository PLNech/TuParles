"""Corpus integrity — catch malformed/un-passable cases at CI time (no GPU/WAV).

Discovered while mining a real take (#83 forensics, 2026-06-24): the scorer's
`normalize()` maps hyphen and apostrophe to space, so a `must_contain` and a
`must_not_contain` that reduce to the SAME tokens make a case impossible to pass
(e.g. "self-contained" vs "self contained" both -> ["self", "contained"]). That
trap is invisible until the GPU run, which CI can't do — so guard it here, pure.
"""

import json
from pathlib import Path

from tuparles.eval import score_case, tokens

CORPUS = Path(__file__).parent / "data" / "codeswitch" / "corpus.json"


def _cases() -> list[dict]:
    return json.loads(CORPUS.read_text())["cases"]


def test_corpus_parses_ids_unique_and_gated():
    cases = _cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in cases:
        assert c.get("text"), f"{c['id']}: empty reference text"
        assert c.get("must_contain"), f"{c['id']}: no must_contain gate"


def test_no_case_is_impossible_to_pass():
    """must_contain and must_not_contain must not share a normalized token tuple,
    else the case can never pass — the hyphen/apostrophe-collapse trap."""
    for c in _cases():
        contain = {tuple(tokens(p)) for p in c.get("must_contain", [])}
        forbid = {tuple(tokens(p)) for p in c.get("must_not_contain", [])}
        clash = contain & forbid
        assert not clash, f"{c['id']}: phrase(s) both required and forbidden: {clash}"


def test_reference_text_passes_its_own_gate():
    """The ground-truth `text` must itself satisfy the gate. If the reference
    can't pass, the case is mis-specified (a typo'd must_contain, a too-broad ban)."""
    for c in _cases():
        result = score_case(c, c["text"])
        assert not result.missing, f"{c['id']}: reference missing {result.missing}"
        assert not result.leaked, f"{c['id']}: reference leaks {result.leaked}"
