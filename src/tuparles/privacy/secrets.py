"""Secret detection: high-signal prefixes (block) + Shannon entropy (alert).

gitleaks-style. Known credential shapes are deterministic and high-precision, so
they MAY block. A generic high-entropy token is a weaker signal (a long hash or
a code identifier can look the same), so it only ALERTs - never auto-redacted.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from tuparles.privacy.core import Finding

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("secret.aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("secret.github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("secret.stripe", re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b")),
    ("secret.openai", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    (
        "secret.jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    ("secret.pem", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

_TOKEN = re.compile(r"\b[A-Za-z0-9+/_=-]{20,}\b")


def _shannon(s: str) -> float:
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def find_secrets(text: str, entropy_threshold: float = 4.0) -> list[Finding]:
    findings: list[Finding] = []
    claimed: list[tuple[int, int]] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            findings.append(Finding(m.start(), m.end(), kind, "block", m.group()))
            claimed.append((m.start(), m.end()))
    for m in _TOKEN.finditer(text):
        if any(s <= m.start() < e for s, e in claimed):
            continue  # already a known-shape secret
        if _shannon(m.group()) >= entropy_threshold:
            findings.append(
                Finding(m.start(), m.end(), "secret.high_entropy", "alert", m.group())
            )
    return findings
