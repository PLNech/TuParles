"""« Comment Tu Parles ? » — the first-launch / post-update micro-onboarding
core (#80, EPIC #55). The pun is the product: TuParles → *comment tu parles ?*

A tiny, skippable card offers a few personalization choices, each with a smart
default already selected ("it's a setting" — total override in Réglages after).
This module is the PURE, testable core: the trigger logic (when to show), the
axes (what to ask), how each choice writes a setting, and a live PREVIEW that
runs the *real* pipeline so the animated card can't show a style the engine
wouldn't actually produce. The Qt carousel is a thin view over this — same split
as the cheat-sheet core/panel (#83).

Three triggers, mirroring what's-new (#82):
  * first launch        — `onboarding_done` is still False → offer every axis;
  * first run post-update — already done, but a release ADDED an axis the user
    has never been offered (tracked in `onboarding_axes_seen`) → offer only the
    new ones, alongside the what's-new card;
  * manual replay       — `axes(force=True)` → always every axis ("Rejouer
    l'intro" in Réglages), so it is never a one-shot you miss.

Graceful by construction: pure Python + settings, no GPU, no heavy deps. The
preview leans on `casing.recase` (#120) so "Ton style" morphs the sample phrase
truthfully; axes whose backing isn't built yet (role packs #90) record the
choice honestly for later rather than faking an effect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tuparles import casing, settings

# The phrase the carousel restyles live — the product's own name as a question.
SAMPLE = "Comment tu parles ?"


@dataclass(frozen=True)
class Choice:
    """One selectable option: the stored `value` and its display `label`."""

    value: str
    label: str


@dataclass(frozen=True)
class Axis:
    """One personalization question. `key` is the setting it writes; `default`
    is pre-selected (skip = keep defaults). `preview(value)` renders the sample
    under a choice for the live card. `apply` writes the chosen value to settings
    (override the default writer for non-scalar settings, e.g. languages)."""

    key: str
    title: str
    question: str
    choices: tuple[Choice, ...]
    default: str
    preview: Callable[[str], str]
    apply: Callable[[str], None]

    def values(self) -> tuple[str, ...]:
        return tuple(c.value for c in self.choices)


# ---- preview renderers (pure; the card animates whatever string they return) --


def _casing_preview(value: str) -> str:
    # The star axis: the same phrase, re-cased by the real #120 engine.
    return casing.recase(SAMPLE, value)


def _view_preview(value: str) -> str:
    return f"▸ {SAMPLE}" if value == "minimal" else SAMPLE


_LANG_PREVIEW = {
    "fr+en": "français + english",
    "fr": "français",
    "en": "english",
    "auto": "auto (100 langues)",
}


def _lang_preview(value: str) -> str:
    return _LANG_PREVIEW.get(value, value)


def _role_preview(value: str) -> str:
    # Since #90: show a REAL macro the role activates ("« lgtm » → LGTM 🚀"),
    # straight from the built-in pack — no faking. "none" (and any role without
    # a pack) names itself honestly.
    from tuparles import rolepacks

    if value == "none":
        return "—"
    sample = rolepacks.example(value)
    return sample if sample else value


def _apply_languages(value: str) -> None:
    codes = {"fr+en": ["fr", "en"], "fr": ["fr"], "en": ["en"], "auto": []}
    settings.put("languages", codes.get(value, []))


def _put(key: str) -> Callable[[str], None]:
    return lambda value: settings.put(key, value)


# ---- the axes, in carousel order -------------------------------------------

AXES: tuple[Axis, ...] = (
    Axis(
        key="casing_style",
        title="Ton style",
        question="Comment tu écris ?",
        choices=(
            Choice("preserve", "Préservé"),
            Choice("lower", "minuscules"),
            Choice("sentence", "Phrase"),
        ),
        default="preserve",
        preview=_casing_preview,
        apply=_put("casing_style"),
    ),
    Axis(
        key="role",
        title="Ton rôle",
        question="Tu fais quoi ?",
        choices=(
            Choice("none", "Aucun"),
            Choice("eng", "Eng"),
            Choice("product", "Product"),
            Choice("design", "Design"),
            Choice("marketing", "Marketing"),
            Choice("strategy", "Strategy"),
        ),
        default="none",
        preview=_role_preview,
        apply=_put("role"),
    ),
    Axis(
        key="languages",
        title="Tes langues",
        question="Tu parles quoi ?",
        choices=(
            Choice("fr+en", "FR + EN"),
            Choice("fr", "FR"),
            Choice("en", "EN"),
            Choice("auto", "Auto"),
        ),
        default="fr+en",
        preview=_lang_preview,
        apply=_apply_languages,
    ),
    Axis(
        key="view",
        title="Ta vue",
        question="Comment tu vois ?",
        choices=(
            Choice("minimal", "Pilule"),
            Choice("full", "Texte complet"),
        ),
        default="minimal",
        preview=_view_preview,
        apply=_put("view"),
    ),
)

_BY_KEY = {a.key: a for a in AXES}


def axes(*, force: bool = False) -> list[Axis]:
    """The axes to offer right now.

    * force (manual replay) → every axis;
    * first launch (`onboarding_done` False) → every axis;
    * otherwise (post-update) → only axes never yet offered (a release added
      one), so a finished user is undisturbed until there's something new.
    """
    if force or not settings.get("onboarding_done"):
        return list(AXES)
    seen = settings.get("onboarding_axes_seen") or []
    return [a for a in AXES if a.key not in seen]


def should_show(*, force: bool = False) -> bool:
    """True iff there is anything to offer (see `axes`)."""
    return bool(axes(force=force))


def defaults() -> dict[str, str]:
    """The pre-selected value per axis — what "Garder les défauts" commits."""
    return {a.key: a.default for a in AXES}


def preview(key: str, value: str) -> str:
    """Render the sample under one choice (the live card reads this)."""
    axis = _BY_KEY.get(key)
    return axis.preview(value) if axis else SAMPLE


def apply_choices(choices: dict[str, str]) -> None:
    """Write each chosen value through its axis, then mark onboarding done.

    Unknown keys and values outside an axis's choices are ignored (the card
    can't submit them, but the core stays total). Marking done records the full
    axis set as seen, so post-update only re-surfaces genuinely new axes.
    """
    for key, value in choices.items():
        axis = _BY_KEY.get(key)
        if axis is not None and value in axis.values():
            axis.apply(value)
    mark_done()


def mark_done() -> None:
    """Record that onboarding ran and which axes the user has now been offered."""
    settings.put("onboarding_done", True)
    settings.put("onboarding_axes_seen", [a.key for a in AXES])
