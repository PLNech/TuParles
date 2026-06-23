"""Reciprocal Rank Fusion -- combine several ranked lists into one.

RRF is the boringly-good choice (innovation tokens spent elsewhere): no score
calibration across signals, robust to one signal being noisy, a single tunable
`k`. A term's fused score is Σ over signals of 1/(k + rank). Terms ranked high
by several signals win; a term only one signal loves still places, just lower.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence


def rrf(rankings: Mapping[str, Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Fuse named ranked key-lists. Returns (key, score) sorted desc."""
    scores: dict[str, float] = defaultdict(float)
    for ranked in rankings.values():
        for rank, key in enumerate(ranked):
            scores[key] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def rrf_contributions(
    rankings: Mapping[str, Sequence[str]], key: str, k: int = 60
) -> dict[str, float]:
    """Per-signal contribution to one key's fused score -- for EDA/explainability."""
    out: dict[str, float] = {}
    for name, ranked in rankings.items():
        try:
            out[name] = 1.0 / (k + ranked.index(key) + 1)
        except ValueError:
            out[name] = 0.0
    return out
