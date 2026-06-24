"""Shared types for the PII firewall.

A `Finding` is one detected span: where it is, what kind, and which tier of
authority it carries. **Tier is the structural safety line** (research:
docs/research/2026-06-24-local-pii-firewall.md): deterministic detectors emit
"block" (they may redact); statistical ones (later, #106) emit "alert" only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    kind: str  # dotted: "secret.aws_key", "pii.iban", "denylist", ...
    tier: str  # "block" (may redact) | "alert" (surface only, never auto-redact)
    text: str  # the matched substring (local-only; for the map / debug)
