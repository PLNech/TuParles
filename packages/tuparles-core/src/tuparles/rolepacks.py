"""Built-in role phrase packs (#90, EPIC #88).

The "Ton rôle" onboarding axis (#80) lets a user pick a role in one tap; this is
what turns that tap into something real. Each role ships a small, curated,
bilingual set of quick-chat macros (the #89 engine), so the choice expands into
live shortcuts without the user first hand-writing a `phrasepack.json`. The
personal pack always takes precedence (see `quickchat.active_phrases`): these are
a *seed you extend*, never a cage.

Two deliberate constraints, both downstream of the house doctrine:

* **More conservative than personal triggers.** A personal macro fires on a
  trigger the user typed themselves, so they know it exists; a role macro arrives
  from a single onboarding tap. The `fullmatch` anchoring in `quickchat` already
  means a trigger only fires when it is the *whole take* — but we still avoid
  bare common words ("nit", "rice") that someone might dictate alone and mean
  literally, preferring distinctive multi-word or acronym triggers. *When in
  doubt, it stays text.*
* **Pure data, no GPU, no deps.** A dict of `Phrase` tuples and two lookups. The
  graceful path is the only path.

Template macros (product "user story", strategy "okr") emit a clean skeleton
with `…` fill-markers rather than literal `<slot>` placeholders — built-ins must
read as finished text, not as a bug. The captured-slot feature (`<name>`) stays
the personal pack's domain, where the user controls both ends.
"""

from __future__ import annotations

from tuparles.quickchat import Phrase

# Curated starter sets. Keep each small and genuinely repetitive-in-chat; the
# user edits/extends via phrasepack.json. Triggers are distinctive on purpose
# (see the conservatism note above); expansions stay close to what you'd type.
_PACKS: dict[str, tuple[Phrase, ...]] = {
    "eng": (
        Phrase("lgtm", "LGTM 🚀", role="eng"),
        Phrase("ship it", "Ship it! 🚢", role="eng"),
        Phrase(
            "ptal", "PTAL — could you take a look when you get a sec? 🙏", role="eng"
        ),
        Phrase("works for me", "Works for me ✅", role="eng"),
    ),
    "product": (
        Phrase(
            "user story",
            "En tant que …, je veux …, afin de …",
            role="product",
        ),
        Phrase(
            "definition of done",
            "Definition of Done :\n- [ ] ",
            role="product",
        ),
        Phrase(
            "rice score",
            "RICE = (Reach × Impact × Confidence) ÷ Effort",
            role="product",
        ),
    ),
    "design": (
        Phrase("non bloquant", "Nit (non-bloquant) : ", role="design"),
        Phrase("looks great", "This looks great ✨", role="design"),
        Phrase("design review", "🎨 Design review : ", role="design"),
    ),
    "marketing": (
        Phrase("call to action", "👉 ", role="marketing"),
        Phrase("tl dr", "TL;DR : ", role="marketing"),
        Phrase("go to market", "GTM : ", role="marketing"),
    ),
    "strategy": (
        Phrase("north star", "North-star metric : ", role="strategy"),
        Phrase("okr", "Objectif : …\nKey results :\n- ", role="strategy"),
        Phrase("tl dr", "TL;DR : ", role="strategy"),
    ),
}


def roles() -> list[str]:
    """The roles that ship a pack (excludes 'none' — the empty role)."""
    return list(_PACKS)


def pack_for(role: str | None) -> list[Phrase]:
    """The built-in macros for `role`; [] for 'none', unknown, or falsy — so an
    unset/empty role activates nothing (the conservative default)."""
    return list(_PACKS.get(role or "", ()))


def example(role: str | None) -> str | None:
    """A short « trigger » → expansion sample from the role's pack, for the
    onboarding preview. None when the role ships nothing (so the card can fall
    back to naming the role honestly rather than faking a macro)."""
    phrases = pack_for(role)
    if not phrases:
        return None
    first = phrases[0]
    expansion = " ".join(first.expansion.split())  # one line for the card
    return f"« {first.trigger} » → {expansion}"
