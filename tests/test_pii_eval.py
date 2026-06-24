"""The PII firewall eval (#104): leakage + over-redaction over a red-team corpus.

Pure text, no GPU — runs in the normal suite, because a regression here is a
privacy regression and must break CI loudly. Two asymmetric gates:

  * LEAKAGE must be ZERO. A planted block-tier secret that survives redaction is
    the cardinal sin — the leaked-key-on-disk threat model itself.
  * OVER-REDACTION must be ZERO too, but for a different reason: the detectors
    are deterministic (checksums, known prefixes, whole-token denylist), so any
    clean span they mask is a real precision bug, not noise.

Each case is parametrised so a single bad case names itself. The aggregate test
prints the scorecard. Grow `tests/data/pii/corpus.json` from every near-miss.
"""

import json
from pathlib import Path

import pytest

from tuparles.privacy import Denylist
from tuparles.privacy.eval import score_case, summarize

CORPUS = Path(__file__).parent / "data" / "pii" / "corpus.json"

# Credential-shaped fixtures are ASSEMBLED here, never stored as literals in the
# tracked corpus — otherwise GitHub's own secret scanner (rightly) blocks the
# push. The irony is the point: a real `sk_live_…` in the file is exactly what
# the firewall exists to stop. The corpus references them by `{{NAME}}` marker.
_SECRETS = {
    "{{AWS}}": "AKIA" + "1234567890ABCDEF",
    "{{GHP}}": "ghp_" + "a" * 36,
    "{{STRIPE}}": "sk_" + "live_" + "a" * 24,
}


def _expand(value):
    if isinstance(value, str):
        for marker, secret in _SECRETS.items():
            value = value.replace(marker, secret)
        return value
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _load_cases() -> list[dict]:
    cases = json.loads(CORPUS.read_text())["cases"]
    for case in cases:
        for key in ("text", "must_redact", "must_keep"):
            if key in case:
                case[key] = _expand(case[key])
    return cases


_DATA = json.loads(CORPUS.read_text())
CASES = _load_cases()
_DL = _DATA.get("denylist", {})
DENYLIST = Denylist.from_terms(
    block=_DL.get("block", []), alert=_DL.get("alert", [])
)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_neither_leaks_nor_over_redacts(case):
    result = score_case(case, denylist=DENYLIST)
    assert not result.leaked, (
        f"LEAKAGE in {case['id']}: {result.leaked} survived → {result.redacted!r}"
    )
    assert not result.over_redacted, (
        f"OVER-REDACTION in {case['id']}: {result.over_redacted} vanished "
        f"→ {result.redacted!r}"
    )


def test_corpus_scorecard():
    """Aggregate gate: the firewall leaks nothing and over-redacts nothing."""
    results = [score_case(c, denylist=DENYLIST) for c in CASES]
    report = summarize(results)
    print(
        f"\nPII eval — {report['cases']} cases | "
        f"leakage {report['leakage_rate']:.0%} {report['leaked_ids']} | "
        f"over-redaction {report['over_redaction_rate']:.0%} "
        f"{report['over_redacted_ids']}"
    )
    assert report["leakage_rate"] == 0.0, f"leaked: {report['leaked_ids']}"
    assert report["over_redaction_rate"] == 0.0, (
        f"over-redacted: {report['over_redacted_ids']}"
    )


def test_corpus_has_red_team_coverage():
    """Guard the corpus itself: it must keep exercising both directions."""
    categories = {c["category"] for c in CASES}
    assert {"secret", "structured", "denylist", "hard-negative"} <= categories
    assert sum(len(c.get("must_redact", [])) for c in CASES) >= 12  # planted PII
    assert any(c["category"] == "codeswitch" for c in CASES)  # the FR+EN case
