"""Read-side aggregations for the Analytics dashboard.

These answer the one question that justifies telemetry at all: *which features
get used, and which are never discovered?* — which feeds deletion-beats-addition.
"""

from __future__ import annotations

from collections import Counter

from tuparles.telemetry import sink


def usage_counts(prefix: str | None = None) -> Counter[str]:
    """How often each event fired, optionally within a group (``"command."``)."""
    counts: Counter[str] = Counter()
    for _ts, name, _attrs in sink.read():
        if prefix is None or name.startswith(prefix):
            counts[name] += 1
    return counts


def first_seen() -> dict[str, str]:
    """Earliest timestamp per event name — when each feature was discovered."""
    seen: dict[str, str] = {}
    for ts, name, _attrs in sink.read():  # DESC order ⇒ last assignment is earliest
        seen[name] = ts
    return seen


def attr_split(name: str, attr: str) -> Counter[str]:
    """Distribution of one attr across one event (e.g. entry path hotkey/tray)."""
    counts: Counter[str] = Counter()
    for _ts, _n, attrs in sink.read(name=name):
        if attr in attrs:
            counts[str(attrs[attr])] += 1
    return counts
