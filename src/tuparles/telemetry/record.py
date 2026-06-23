"""The primitives the app calls: event() and timer().

All gated by a local opt-out (settings `telemetry_enabled`, default True).
When disabled, every primitive is a no-op — no rows written, no cost. Telemetry
is local-only, so default-on is honest: nothing is ever transmitted, and the
user holds a single kill-switch (#99).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from tuparles import settings
from tuparles.telemetry import sink

_SETTING = "telemetry_enabled"


def enabled() -> bool:
    val = settings.get(_SETTING)
    return True if val is None else bool(val)


def set_enabled(on: bool) -> None:
    settings.put(_SETTING, bool(on))


def event(name: str, /, **attrs: object) -> None:
    """Record a feature-usage event (e.g. ``event("command.fired", name="undo")``).

    The event name is positional-only, so a ``name=`` attr never collides with
    it. No-op when telemetry is disabled. Names are dotted for grouping
    (``command.*``, ``syntax.*``, ``mode.*``, ``entry.*``).
    """
    if not enabled():
        return
    sink.write(name, attrs)


@contextmanager
def timer(name: str, /, **attrs: object) -> Iterator[None]:
    """Time a block and record `name` with an ``elapsed_s`` attr.

    No-op (still yields) when telemetry is disabled, so call sites stay clean.
    """
    if not enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        sink.write(name, {**attrs, "elapsed_s": round(time.perf_counter() - start, 4)})
