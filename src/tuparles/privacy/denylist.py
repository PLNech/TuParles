"""User denylist: named clients / projects / words a model never knows.

Token-level matching on normalized text, so it is **word-boundary by
construction** (the canonical Scunthorpe fix - "Pénistone" never trips a "penis"
entry because we compare whole tokens, not substrings). Two tiers: block (may
redact) and alert (surface only). v1 matches single tokens; multi-word phrase
entries are a documented follow-up.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from tuparles.privacy.core import Finding
from tuparles.privacy.normalize import normalize

_WORD = re.compile(r"\w[\w'-]*", re.UNICODE)


@dataclass
class Denylist:
    block: set[str] = field(default_factory=set)  # normalized terms
    alert: set[str] = field(default_factory=set)

    @classmethod
    def from_terms(
        cls, block: Iterable[str] = (), alert: Iterable[str] = ()
    ) -> Denylist:
        return cls(
            block={normalize(t) for t in block},
            alert={normalize(t) for t in alert},
        )

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for m in _WORD.finditer(text):
            n = normalize(m.group())
            if n in self.block:
                findings.append(Finding(m.start(), m.end(), "denylist", "block", m.group()))
            elif n in self.alert:
                findings.append(Finding(m.start(), m.end(), "denylist", "alert", m.group()))
        return findings
