"""Structured PII via checksum validators (rent python-stdnum).

Email + checksummable numbers (IBAN ISO 7064, French NIR with its control key
incl. Corsica 2A/2B, credit-card Luhn). Checksum-validated => ~100% precision,
so these MAY block. We rent stdnum rather than hand-roll the FR NIR edge cases.
"""

from __future__ import annotations

import re

from stdnum import iban, luhn
from stdnum.fr import nir

from tuparles.privacy.core import Finding

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# A candidate token, validated by checksum before it counts. Contiguous (no
# spaces) so it never gobbles across tokens; space-separated IBANs ("FR14 2004
# …") are a documented follow-up (compact-form IBANs are the common case).
_CANDIDATE = re.compile(r"\b[0-9A-Za-z]{10,34}\b")


def find_structured(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for m in _EMAIL.finditer(text):
        findings.append(Finding(m.start(), m.end(), "pii.email", "block", m.group()))
    for m in _CANDIDATE.finditer(text):
        raw = m.group()
        compact = raw.replace(" ", "")
        if iban.is_valid(compact):
            findings.append(Finding(m.start(), m.end(), "pii.iban", "block", raw))
        elif nir.is_valid(compact):
            findings.append(Finding(m.start(), m.end(), "pii.fr_nir", "block", raw))
        elif compact.isdigit() and 12 <= len(compact) <= 19 and luhn.is_valid(compact):
            findings.append(Finding(m.start(), m.end(), "pii.card", "block", raw))
    return findings
