"""Frequency floor: irreversible minimization for aggregates.

For analytics tag-clouds and seeded dicts, per-message redaction is the wrong
tool - the risk is a rare term (a name said once) surfacing as "vocabulary". The
fix is k-anonymity reduced to its single-user essence: **suppress the long
tail**. Drop any term seen fewer than k times. Boring, proportionate, done.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping


def frequency_floor(counts: Mapping[str, int], k: int = 2) -> Counter[str]:
    """Keep only terms with count >= k. A name uttered once never surfaces."""
    return Counter({term: n for term, n in counts.items() if n >= k})
