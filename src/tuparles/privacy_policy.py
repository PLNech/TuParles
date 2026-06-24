"""Settings-aware glue over the pure PII core (#115).

The `privacy/` package is the rentable, standalone spine: no settings, no I/O,
no model. This module is the one-level-out adapter that reads the user's
Réglages and drives the core over the live paths (utterance persist, analytics).

The split that matters: we deliver dictation VERBATIM (the paste hot-path is
never touched — you get exactly what you said), then minimize *before persist*.
So a secret you dictate lands in the focused app but never in history.db.
"""

from __future__ import annotations

from tuparles import privacy, settings
from tuparles.privacy import Denylist


def active_denylist() -> Denylist | None:
    """Build the user's denylist from settings, or None if both lists empty.

    Empty-by-default: the deterministic detectors (secrets + structured) carry
    the firewall on their own; the denylist is purely opt-in personal terms.
    """
    block = settings.get("pii_denylist_block") or []
    alert = settings.get("pii_denylist_alert") or []
    if not block and not alert:
        return None
    return Denylist.from_terms(block=block, alert=alert)


def redact_for_storage(text: str) -> str:
    """Mask block-tier PII before a transcript is persisted.

    Off → text unchanged (the toggle is `pii_redact_history`, default on). On →
    secrets + checksum-validated structured PII + denylist-block spans become
    `<KIND>` placeholders. Alert-tier is never masked here. The verbatim text
    has already been delivered upstream; this only shapes what we keep.
    """
    if not settings.get("pii_redact_history"):
        return text
    return privacy.redact(text, denylist=active_denylist())


def analytics_min_count() -> int:
    """The k-floor applied to the utterance tag cloud (k-anonymity over names).

    Default 1 keeps short clouds non-empty (dictations are terse); raise it so a
    once-spoken name can't surface. Block-tier PII is already gone from the
    corpus — it was stripped at persist — so this floor only guards rare terms.
    """
    try:
        return max(1, int(settings.get("pii_analytics_min_count") or 1))
    except (TypeError, ValueError):
        return 1
