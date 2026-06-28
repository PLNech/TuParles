"""Scoring for the PII firewall eval corpus (#104).

Pure text, no model, no GPU — so the leakage harness runs in the normal suite.
Two asymmetric metrics, mirroring the project's safety doctrine:

  * LEAKAGE (recall miss) — a planted block-tier secret that survived redaction.
    This is the cardinal sin: it must be zero. A leaked AWS key on disk is the
    whole threat model.
  * OVER-REDACTION (precision miss) — clean text the firewall masked anyway.
    The "a wrong autocorrect is worse than a visible mishear" cost: a git SHA,
    a non-Luhn 16-digit order number, or a Scunthorpe word wrongly redacted.

`must_redact` substrings MUST be absent from the redacted output; `must_keep`
substrings MUST survive it. The harness aggregates both into rates.
"""

from __future__ import annotations

from dataclasses import dataclass

from tuparles.privacy.denylist import Denylist
from tuparles.privacy.redact import redact


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    redacted: str
    leaked: list[str]  # must_redact spans that survived (FN — the cardinal sin)
    over_redacted: list[str]  # must_keep spans that vanished (FP — over-zeal)

    @property
    def clean(self) -> bool:
        return not self.leaked and not self.over_redacted


def score_case(case: dict, denylist: Denylist | None = None) -> CaseResult:
    """Redact one corpus case and check both directions against its labels."""
    redacted = redact(case["text"], denylist=denylist)
    leaked = [s for s in case.get("must_redact", []) if s in redacted]
    over = [s for s in case.get("must_keep", []) if s not in redacted]
    return CaseResult(case["id"], redacted, leaked, over)


def summarize(results: list[CaseResult]) -> dict:
    """Aggregate leakage + over-redaction rates over a run."""
    total = len(results)
    leaked = [r for r in results if r.leaked]
    over = [r for r in results if r.over_redacted]
    return {
        "cases": total,
        "leaked_cases": len(leaked),
        "over_redacted_cases": len(over),
        "leakage_rate": len(leaked) / total if total else 0.0,
        "over_redaction_rate": len(over) / total if total else 0.0,
        "leaked_ids": [r.case_id for r in leaked],
        "over_redacted_ids": [r.case_id for r in over],
    }
