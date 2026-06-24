"""Scan + redact: the deterministic orchestrator.

`scan()` gathers findings from every deterministic detector; `redact()` masks
the **block-tier** spans with a `<KIND>` placeholder (self-documenting, our
"visible mishear > silent rewrite" principle). Alert-tier findings are returned
for the caller to surface, never auto-redacted. The reversible-map LLM firewall
and the statistical net build on top (#105, #106).
"""

from __future__ import annotations

from tuparles.privacy.core import Finding
from tuparles.privacy.denylist import Denylist
from tuparles.privacy.secrets import find_secrets
from tuparles.privacy.structured import find_structured


def scan(text: str, denylist: Denylist | None = None) -> list[Finding]:
    findings = find_secrets(text) + find_structured(text)
    if denylist is not None:
        findings += denylist.scan(text)
    return sorted(findings, key=lambda f: f.start)


def redact(
    text: str,
    findings: list[Finding] | None = None,
    denylist: Denylist | None = None,
) -> str:
    """Mask every block-tier span with `<KIND>`. Overlaps: first span wins."""
    if findings is None:
        findings = scan(text, denylist)
    blocks = sorted(
        (f for f in findings if f.tier == "block"), key=lambda f: (f.start, -f.end)
    )
    out: list[str] = []
    last = 0
    for f in blocks:
        if f.start < last:  # overlapping a span we already masked
            continue
        out.append(text[last : f.start])
        out.append(f"<{f.kind.upper()}>")
        last = f.end
    out.append(text[last:])
    return "".join(out)
