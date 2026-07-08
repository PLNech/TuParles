"""Unit tests for scripts/score_transcript_entities.py.

Everything here runs on SYNTHETIC fixtures invented for the test — never real
transcripts. The fixture plants each entity's correct form and its known-wrong
variant(s) a known number of times so the expected counts are exact. Names
that would identify a real meeting are replaced by fictional ones (FluxiCare,
7QZXK9P2LM) exercised through the custom-spec path.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "score_transcript_entities.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("score_transcript_entities", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module uses `from __future__ import annotations`
    # + dataclasses, which resolves string annotations via sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# A synthetic transcript-like string covering the built-in (default) spec.
# Fake sentences, invented for the test. Planted counts annotated inline.
FIXTURE = (
    "On compare Opus et OPUZ, puis K-8 encore une fois. "  # Opus1 / OPUZ1 / K-8 1
    "Haiku vs Aiku. Gemini vs Gmini. Gemma vs GEMA. DeepSeek vs Dipsy. "
    "n8n contre N8AIN. Anthropic, Anthropy, et en tropique. "
    "Datadog puis Data Dog. Nemotron et Némotron, mais motrons ailleurs. "
    "Doctolib mais doctolibre. "
    "Une query, deux queries, une quarry, des quéris. "  # query2 / quarry1 / quéris1
    "Algolia, Claude, PostHog présents."
)

EXPECTED = {
    "Algolia": {"correct": 1, "wrong": {}, "wrong_total": 0},
    "Opus": {"correct": 1, "wrong": {"OPUZ": 1, "K-8": 1}, "wrong_total": 2},
    "Haiku": {"correct": 1, "wrong": {"Aiku": 1}, "wrong_total": 1},
    "Gemini": {"correct": 1, "wrong": {"Gmini": 1}, "wrong_total": 1},
    "Gemma": {"correct": 1, "wrong": {"GEMA": 1}, "wrong_total": 1},
    "DeepSeek": {"correct": 1, "wrong": {"Dipsy": 1}, "wrong_total": 1},
    "n8n": {"correct": 1, "wrong": {"N8AIN": 1}, "wrong_total": 1},
    "Anthropic": {
        "correct": 1,
        "wrong": {"Anthropy": 1, "en tropique": 1},
        "wrong_total": 2,
    },
    "Claude": {"correct": 1, "wrong": {}, "wrong_total": 0},
    "Datadog": {"correct": 1, "wrong": {"Data Dog": 1}, "wrong_total": 1},
    "PostHog": {"correct": 1, "wrong": {}, "wrong_total": 0},
    "Nemotron": {"correct": 2, "wrong": {"motrons": 1}, "wrong_total": 1},
    "Doctolib": {"correct": 1, "wrong": {"doctolibre": 1}, "wrong_total": 1},
    "query": {"correct": 2, "wrong": {"quarry": 1, "quéris": 1}, "wrong_total": 2},
}


def _custom_spec(mod):
    """A meeting-style custom spec with fully fictional entities."""
    return [
        mod.Entity(
            "FluxiCare",
            correct=[mod.Variant("FluxiCare", case_sensitive=True)],
            wrong=[
                mod.Variant("Fluxicare", case_sensitive=True),
                mod.Variant("FLUX-icare"),
            ],
        ),
        mod.Entity(
            "7QZXK9P2LM",
            correct=[mod.Variant("7QZXK9P2LM")],
            wrong=[mod.Variant("7QZXK")],
        ),
    ]


def test_full_score_matches_expected(mod):
    assert mod.score_text(FIXTURE) == EXPECTED


def test_default_spec_has_no_meeting_specific_entities(mod):
    # The committed default spec must stay generic: brands only, no customer
    # names, no app IDs. Those arrive via --spec at run time.
    names = {e.name for e in mod.ENTITY_SPEC}
    assert names == set(EXPECTED)


def test_substring_boundaries_do_not_double_count(mod):
    # The truncated ID must not fire inside the full one; "Doctolib" must not
    # fire inside "doctolibre"; the "Data Dog" split must not be seen as
    # "Datadog".
    r = mod.score_text("doctolibre Data Dog")
    assert r["Doctolib"]["correct"] == 0
    assert r["Doctolib"]["wrong"]["doctolibre"] == 1
    assert r["Datadog"]["correct"] == 0
    assert r["Datadog"]["wrong"]["Data Dog"] == 1

    r2 = mod.score_text("l'app 7QZXK9P2LM tourne", spec=_custom_spec(mod))
    assert r2["7QZXK9P2LM"]["correct"] == 1
    assert r2["7QZXK9P2LM"]["wrong"]["7QZXK"] == 0

    r3 = mod.score_text("l'app 7QZXK tourne", spec=_custom_spec(mod))
    assert r3["7QZXK9P2LM"]["correct"] == 0
    assert r3["7QZXK9P2LM"]["wrong"]["7QZXK"] == 1


def test_hyphen_and_space_both_match(mod):
    # Multi-word / hyphenated forms match across either separator.
    r = mod.score_text("Data-Dog and Data Dog; K 8 and K-8")
    assert r["Datadog"]["wrong"]["Data Dog"] == 2
    assert r["Opus"]["wrong"]["K-8"] == 2

    r2 = mod.score_text("FLUX icare et FLUX-icare", spec=_custom_spec(mod))
    assert r2["FluxiCare"]["wrong"]["FLUX-icare"] == 2


def test_case_sensitivity_where_case_is_the_error(mod):
    # Lowercase "opus" is still the correct entity (case-insensitive), but
    # "OPUZ" is only counted when all-caps.
    r = mod.score_text("opus opuz OPUZ")
    assert r["Opus"]["correct"] == 1  # "opus" matches; "opuz"/"OPUZ" are not Opus
    assert r["Opus"]["wrong"]["OPUZ"] == 1  # only the all-caps mangle

    # "Fluxicare" (cap F, lower c) and "FluxiCare" (cap C) are distinct;
    # an all-lowercase "fluxicare" is counted as neither.
    r2 = mod.score_text("FluxiCare Fluxicare fluxicare", spec=_custom_spec(mod))
    assert r2["FluxiCare"]["correct"] == 1
    assert r2["FluxiCare"]["wrong"]["Fluxicare"] == 1


def test_accent_and_plural_aliases_count_as_correct(mod):
    r = mod.score_text("Nemotron Némotron query queries")
    assert r["Nemotron"]["correct"] == 2
    assert r["query"]["correct"] == 2


def test_load_spec_roundtrip(mod, tmp_path):
    # The --spec JSON format loads into the same behaviour as built objects.
    spec_json = [
        {
            "name": "FluxiCare",
            "correct": [{"form": "FluxiCare", "case_sensitive": True}],
            "wrong": [
                {"form": "Fluxicare", "case_sensitive": True},
                {"form": "FLUX-icare"},
            ],
        },
        {
            "name": "7QZXK9P2LM",
            "correct": [{"form": "7QZXK9P2LM"}],
            "wrong": [{"form": "7QZXK"}],
        },
    ]
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec_json), encoding="utf-8")
    spec = mod.load_spec(p)

    text = "FluxiCare, Fluxicare, un FLUX-icare, l'app 7QZXK9P2LM alias 7QZXK."
    assert mod.score_text(text, spec=spec) == {
        "FluxiCare": {
            "correct": 1,
            "wrong": {"Fluxicare": 1, "FLUX-icare": 1},
            "wrong_total": 2,
        },
        "7QZXK9P2LM": {"correct": 1, "wrong": {"7QZXK": 1}, "wrong_total": 1},
    }


def test_load_spec_rejects_non_list(mod, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"name": "X"}', encoding="utf-8")
    with pytest.raises(ValueError):
        mod.load_spec(p)


def test_score_file_reads_and_returns_counts_only(mod, tmp_path):
    p = tmp_path / "synthetic-transcript.txt"
    p.write_text(FIXTURE, encoding="utf-8")
    result = mod.score_file(p)
    assert result == EXPECTED
    # Structural redaction guarantee: output holds only ints, no transcript text.
    for counts in result.values():
        assert isinstance(counts["correct"], int)
        assert all(isinstance(v, int) for v in counts["wrong"].values())
