"""Voice command meta-language: a narrow, deterministic, LOCAL command layer
over dictation.

This is the honest answer to cloud "agent modes" (Genspark Speakly's
double-tap → a cloud agent does a task): no round-trip, no model, no
surprises. A take is EITHER text to deliver OR one of a small, fixed set of
edit commands — never a probabilistic guess about intent. The whole design is
built to NOT misfire on prose: catching a command that wasn't meant is far
worse than missing one (a missed command just gets typed, and you retry).

Activation is pure-voice and structural:
  - DELETE requires a DOUBLED trigger word ("efface efface", "delete delete").
    Nobody says that in prose, so the doubling IS the safety interlock.
  - UNDO / NUDGE / open-terminal are a tiny whitelist of short exact phrases.
  - A take longer than a few words is always text (commands are terse).
  - A literal-escape prefix ('dis ...', 'say ...') forces text — BUT only when
    what follows would otherwise BE a command, so it never hijacks prose that
    merely starts with "dis".

Bilingual by design (FR + EN): code-switching is the moat, so the grammar
accepts either language interchangeably. The richer held-modifier "command
quasimode" (a held second modifier = the next words are a command) is a
deliberate follow-up; this pure-voice layer ships and tests without touching
the hotkey path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Commands are terse. Anything longer than this many words is prose, full
# stop — the single cheapest, strongest guard against misfiring on dictation.
MAX_COMMAND_TOKENS = 7

# Delete needs a DOUBLED trigger. The surface forms a French/English speaker
# actually reaches for; imperative and infinitive both ("efface"/"effacer").
_DELETE_TRIGGERS = {
    "efface", "effacer", "effaces",
    "supprime", "supprimer", "supprimes",
    "delete", "remove", "erase",
}

# Units of deletion, mapped to the canonical name the executor understands.
_UNITS = {
    "mot": "word", "mots": "word", "word": "word", "words": "word",
    "caractère": "char", "caractères": "char",
    "caractere": "char", "caracteres": "char",
    "lettre": "char", "lettres": "char",
    "char": "char", "chars": "char",
    "character": "char", "characters": "char",
    "ligne": "line", "lignes": "line", "line": "line", "lines": "line",
    "tout": "all", "everything": "all", "all": "all",
}

# Whole-take phrases (after normalization) that map to a single safe action.
# Undo is reversible and inherently safe, so it needs no doubling.
_UNDO_PHRASES = {"annule", "annuler", "annulation", "undo"}

# Nudge tweaks the LAST edit. Only the explicit multi-word forms — never a
# bare "plus"/"more", which collides with prose. "encore" is deliberately
# excluded (too polysemous).
_NUDGE_MORE = {
    "un peu plus", "encore un peu", "a bit more", "a little more", "un cran plus",
}
_NUDGE_LESS = {
    "un peu moins", "a bit less", "a little less", "un cran moins",
}

_OPEN_TERMINAL = {
    "ouvre un terminal", "ouvre le terminal", "ouvre-moi un terminal",
    "ouvre moi un terminal", "nouveau terminal",
    "open a terminal", "open terminal", "new terminal",
}

# Literal-escape prefixes: "dictate the next words, don't interpret them".
_LITERAL_PREFIXES = (
    "dis", "écris", "ecris", "tape",
    "say", "type", "write", "verbatim",
    "littéralement", "litteralement",
)

_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six_en": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# "six" collides FR/EN — same value, so one entry is enough; the _en marker
# above is never matched (kept only so the EN list reads complete).

# Trailing/leading punctuation the spoken-punctuation or decode pass may have
# glued on ("efface efface." → "efface efface"). Stripped before matching.
_EDGE_PUNCT = " \t\n.,;:!?…\"'»«“”’()[]"


@dataclass(frozen=True)
class Command:
    """A parsed voice command. `action` selects the branch; the other fields
    carry its parameters. action="literal" means 'not a command after all —
    deliver `text` as ordinary dictation' (the result of a literal-escape)."""

    action: str  # "delete" | "undo" | "nudge" | "open_terminal" | "literal"
    unit: str = "word"  # delete: word | char | line | all
    count: int = 1  # delete: how many units
    direction: str = "more"  # nudge: more | less
    text: str = ""  # literal: the text to deliver instead


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip edge punctuation. The form all
    matching is done against — never shown to the user, never delivered."""
    return re.sub(r"\s+", " ", text).strip(_EDGE_PUNCT).strip().casefold()


def _strip_quotes(text: str) -> str:
    return text.strip().strip("\"'«»“”’ ").strip()


def _parse_count(tokens: list[str]) -> int | None:
    """First explicit number among `tokens` (digit or FR/EN word), or None."""
    for tok in tokens:
        if tok.isdigit():
            return int(tok)
        if tok in _NUMBER_WORDS:
            return _NUMBER_WORDS[tok]
    return None


def _parse_unit(tokens: list[str]) -> str | None:
    """First recognized unit keyword among `tokens`, or None."""
    for tok in tokens:
        if tok in _UNITS:
            return _UNITS[tok]
    return None


def _parse_delete(tokens: list[str]) -> Command | None:
    """A doubled delete trigger at the start, then optional unit/count.
    Returns None if the take doesn't open with two delete triggers."""
    n_triggers = 0
    for tok in tokens:
        if tok in _DELETE_TRIGGERS:
            n_triggers += 1
        else:
            break
    if n_triggers < 2:
        return None  # no doubling → not a delete; the safety interlock

    rest = tokens[n_triggers:]
    unit = _parse_unit(rest) or "word"
    explicit = _parse_count(rest)
    if unit == "all":
        return Command("delete", unit="all", count=1)
    # Explicit number wins; otherwise each trigger past the activating pair is
    # one more unit ("efface efface" = 1, "efface efface efface" = 2).
    count = explicit if explicit is not None else max(1, n_triggers - 1)
    return Command("delete", unit=unit, count=count)


def _parse_simple(norm: str) -> Command | None:
    """Whole-take exact-match commands: undo, nudge, open-terminal."""
    if norm in _UNDO_PHRASES:
        return Command("undo")
    if norm in _NUDGE_MORE:
        return Command("nudge", direction="more")
    if norm in _NUDGE_LESS:
        return Command("nudge", direction="less")
    if norm in _OPEN_TERMINAL:
        return Command("open_terminal")
    return None


def _parse_core(norm: str) -> Command | None:
    """Parse a normalized take into a NON-literal command, or None for prose.
    Shared by the public parse() and the literal-escape look-ahead, so escape
    can ask 'would this remainder be a command?' without recursing into itself.
    """
    if not norm:
        return None
    tokens = norm.split(" ")
    if len(tokens) > MAX_COMMAND_TOKENS:
        return None  # too long to be a command — it's dictation
    return _parse_simple(norm) or _parse_delete(tokens)


def parse(text: str) -> Command | None:
    """Classify a finished take: a Command to execute, or None to deliver as
    ordinary text. Biased hard toward None — when nothing matches cleanly, it
    is dictation. The one rule with teeth: delete needs a doubled trigger."""
    norm = _normalize(text)
    if not norm:
        return None

    # Literal escape: 'dis "efface efface"' → deliver "efface efface" as text.
    # Fires ONLY when the remainder would itself parse as a command, so a
    # sentence that merely starts with "dis"/"say" is left as normal prose.
    first, _, remainder = text.strip().partition(" ")
    if first.strip(_EDGE_PUNCT).casefold() in _LITERAL_PREFIXES and remainder:
        inner = _strip_quotes(remainder)
        if _parse_core(_normalize(inner)) is not None:
            return Command("literal", text=inner)

    return _parse_core(norm)
