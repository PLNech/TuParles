"""Spoken-syntax core: the framework every structured-dictation family plugs
into (quotes, capitalization, lists, code fences — EPIC #53).

A *feature* is a deterministic text transformation you trigger by voice INSIDE
a take. That's the line between this and `commands.py`: an edit command (#41)
is a whole take that IS an instruction ("efface efface") and produces no text;
a syntax feature rewrites *part of* the dictated text and the rest is delivered
normally. So features live in the post-decode text pipeline, not the command
layer.

Two guarantees this core provides so no family reinvents them:

1. **Safety is structural, and it lives in the feature.** There is no universal
   interlock here — quotes pair, capitalization marks the next word, lists key
   off line starts. What the core gives each family is the *place to hang* its
   interlock and a hard contract: a feature is settings-gated, ships a
   conservative default, and may NEVER crash a take. The doctrine it inherits
   from #41 is absolute and asymmetric: *when in doubt, it's text.* Editing the
   user's prose against their will is unforgivable; missing a command is a
   shrug-and-retry.

2. **Everything is a setting.** A feature declares `default_enabled`; the core
   consults `settings["syntax"][name]` for an override. Smart default on, total
   control in Réglages. "It's a setting again."

Features `register()` and run, in declared `order`, via `apply_syntax()`.
Output formatting (markdown vs plain, per focused app) is a `SyntaxContext` the
core threads through but does not itself decide — that's the output-format
engine (#58). Until then, and wherever detection fails, the context is `plain`
so we never surprise a plain text field with stray markup.

Families register on import; whatever assembles the pipeline imports them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tuparles import settings


@dataclass(frozen=True)
class SyntaxContext:
    """What a feature needs to know about the destination.

    `fmt` is the output target ("plain" or "markdown"); markup-emitting families
    (lists, fences) degrade to plain when it's "plain". `app_class` is the
    focused window's class when known, for features that want finer control.
    """

    fmt: str = "plain"
    app_class: str | None = None


@dataclass(frozen=True)
class SyntaxFeature:
    """A registered transformation. `apply(text, ctx) -> text` must be pure and
    total (handle any string); `order` sets run position (low runs first).

    `summary` and `triggers` are the feature's own help (the cheat-sheet, #83):
    a one-line description and a few representative spoken forms. They live with
    the feature — same place as its regex — so help can't drift from grammar."""

    name: str
    apply: Callable[[str, SyntaxContext], str]
    default_enabled: bool = True
    order: int = 100
    summary: str = ""
    triggers: tuple[str, ...] = ()


_FEATURES: list[SyntaxFeature] = []


def register(feature: SyntaxFeature) -> None:
    """Add (or replace, by name) a feature. Replacing-by-name makes re-import
    under hot-reload or tests idempotent rather than double-running a family."""
    global _FEATURES
    _FEATURES = [f for f in _FEATURES if f.name != feature.name]
    _FEATURES.append(feature)


def clear() -> None:
    """Drop every registered feature (tests)."""
    _FEATURES.clear()


def registered() -> list[str]:
    """Names in run order — the source of truth for the cheat-sheet (#83)."""
    return [f.name for f in _ordered()]


def catalogue() -> list[SyntaxFeature]:
    """Registered features in run order — for the cheat-sheet (#83) to read each
    family's `summary`/`triggers` help. A copy of the list so callers can't
    mutate the registry."""
    return list(_ordered())


def _ordered() -> list[SyntaxFeature]:
    # Stable sort: ties keep registration order, so a family can pin itself
    # before/after another without fighting over exact numbers.
    return sorted(_FEATURES, key=lambda f: f.order)


def feature_enabled(name: str, default: bool) -> bool:
    """Per-feature toggle. Settings shape: {"syntax": {"<name>": bool}}.
    Absent or malformed → the feature's own default."""
    cfg = settings.get("syntax")
    if not isinstance(cfg, dict):
        return default
    val = cfg.get(name)
    return default if val is None else bool(val)


def apply_syntax(
    text: str,
    ctx: SyntaxContext | None = None,
    on_fire: Callable[[str], None] | None = None,
) -> str:
    """Run every enabled feature, in order, threading `ctx`.

    Best-effort per feature: one that raises is logged and skipped, never
    taking down the take (same contract as delivery). An empty registry is the
    identity, so this is safe to call before any family exists.

    `on_fire(name)` is an optional side-effect hook, called when a feature
    actually changed the text. The daemon injects telemetry through it; the
    eval harness passes nothing, so this function stays pure for measurement.
    """
    if ctx is None:
        ctx = SyntaxContext()
    for feature in _ordered():
        if not feature_enabled(feature.name, feature.default_enabled):
            continue
        before = text
        try:
            text = feature.apply(text, ctx)
        except Exception as exc:
            print(f"syntax feature {feature.name!r} failed: {str(exc)[:120]}")
            continue
        if on_fire is not None and text != before:
            on_fire(feature.name)
    return text
