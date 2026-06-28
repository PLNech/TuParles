"""Structured PII via checksum validators (rent python-stdnum).

Email + checksummable numbers (IBAN ISO 7064, French NIR with its control key
incl. Corsica 2A/2B, credit-card Luhn). Checksum-validated => ~100% precision,
so these MAY block. We rent stdnum rather than hand-roll the FR NIR edge cases.
"""

from __future__ import annotations

import re
from typing import Any

from tuparles.privacy.core import Finding

_iban: Any
_luhn: Any
_nir: Any
try:
    from stdnum import iban as _iban
    from stdnum import luhn as _luhn
    from stdnum.fr import nir as _nir
except ImportError:
    _iban = None
    _luhn = None
    _nir = None

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# A candidate token, validated by checksum before it counts. Contiguous (no
# spaces) so it never gobbles across tokens; space-separated IBANs ("FR14 2004
# …") are a documented follow-up (compact-form IBANs are the common case).
_CANDIDATE = re.compile(r"\b[0-9A-Za-z]{10,34}\b")


def _is_card(digits: str) -> bool:
    """A real card number, not a Luhn coincidence.

    Luhn alone passes ~1-in-10 random digit strings, so for BLOCK authority we
    also require a genuine network IIN prefix *and* a length that network
    actually issues. This is what keeps a 15-digit order number that happens to
    pass Luhn from being masked as an Amex (the #104 eval caught exactly that).
    """
    n = len(digits)
    if _luhn is None or not _luhn.is_valid(digits):
        return False
    if digits[0] == "4":  # Visa
        return n in (13, 16, 19)
    if digits[:2] in {"34", "37"}:  # American Express
        return n == 15
    if 51 <= int(digits[:2]) <= 55 or 2221 <= int(digits[:4]) <= 2720:  # Mastercard
        return n == 16
    if digits[:4] == "6011" or digits[:2] == "65" or 644 <= int(digits[:3]) <= 649:
        return n in (16, 19)  # Discover
    if digits[:2] == "62":  # UnionPay
        return 16 <= n <= 19
    if digits[:2] in {"36", "38", "39"} or 300 <= int(digits[:3]) <= 305:  # Diners
        return n in (14, 16, 19)
    if 3528 <= int(digits[:4]) <= 3589:  # JCB
        return n in (16, 19)
    return False


def find_structured(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for m in _EMAIL.finditer(text):
        findings.append(Finding(m.start(), m.end(), "pii.email", "block", m.group()))
    for m in _CANDIDATE.finditer(text):
        raw = m.group()
        compact = raw.replace(" ", "")
        if _iban is not None and _iban.is_valid(compact):
            findings.append(Finding(m.start(), m.end(), "pii.iban", "block", raw))
        elif _nir is not None and _nir.is_valid(compact):
            findings.append(Finding(m.start(), m.end(), "pii.fr_nir", "block", raw))
        elif compact.isdigit() and 12 <= len(compact) <= 19 and _is_card(compact):
            findings.append(Finding(m.start(), m.end(), "pii.card", "block", raw))
    return findings
