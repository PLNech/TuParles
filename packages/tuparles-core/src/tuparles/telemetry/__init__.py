"""Local, opt-out usage introspection for TuParles.

A small modular layer that mirrors `nlp/`'s shape:

    record   ->  event() / timer() primitives, gated by a local opt-out
    sink     ->  a sibling `events` table in the tuparles data store
    readout  ->  usage / discovery aggregations for the Analytics dashboard

Local-only by doctrine: events never leave the machine. This is single-user
introspection — "which features do *I* actually use?" — not beta analytics, so
there is no consent or transport layer to get wrong.
"""

from tuparles.telemetry.record import enabled, event, set_enabled, timer
from tuparles.telemetry.sink import clear

__all__ = ["clear", "enabled", "event", "set_enabled", "timer"]
