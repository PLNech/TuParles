"""Local PII firewall - the deterministic core (#103).

Minimize before persist / analyze / send, all on the user's box. This phase is
the high-assurance, no-model / no-torch layer: secret prefixes + entropy,
checksum-validated structured PII (python-stdnum), a user denylist, and a
frequency floor for aggregates. Deterministic detectors carry block authority;
the statistical net (topic-alert + NER) and the reversible LLM firewall build
on top (#105, #106). See docs/research/2026-06-24-local-pii-firewall.md.
"""

from tuparles.privacy.core import Finding
from tuparles.privacy.denylist import Denylist
from tuparles.privacy.floor import frequency_floor
from tuparles.privacy.redact import redact, scan
from tuparles.privacy.secrets import find_secrets
from tuparles.privacy.structured import find_structured

__all__ = [
    "Denylist",
    "Finding",
    "find_secrets",
    "find_structured",
    "frequency_floor",
    "redact",
    "scan",
]
