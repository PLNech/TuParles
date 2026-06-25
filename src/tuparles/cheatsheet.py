"""Cheat-sheet core (#83): one searchable, bilingual reference of every voice
command and syntax phrase — DERIVED from the live grammar, never hard-coded.

Three sources of truth, read at call time so the sheet can't drift from code:
  * commands.vocabulary()         — the voice-command meta-language (#41)
  * punctuation.SPOKEN_TO_SYMBOL  — spoken punctuation
  * syntax.catalogue()            — registered spoken-syntax families (#53)

Pure and dependency-free: the CLI (`tuparles cheatsheet`) and a future tray
panel both render the same `entries()`, so they can never show different help.
A new spoken command nobody can discover is a command that does not exist.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from tuparles import (
    commands,
    punctuation,
    quickchat,
    settings,
    syntax,
    syntax_features,  # noqa: F401  (import = register families)
)


@dataclass(frozen=True)
class CheatEntry:
    """One reference row: what to say, and the one-line how/why."""

    category: str  # "Commandes" | "Ponctuation" | "Syntaxe"
    title: str
    triggers: tuple[str, ...]
    note: str = ""

    def haystack(self) -> str:
        """Everything `search` matches against, in one string."""
        return " ".join((self.category, self.title, *self.triggers, self.note))


# --- punctuation: turn the matching regexes into readable spoken phrases ------


def _class_repl(match: re.Match[str]) -> str:
    """A `[...]` char class → the one readable character it stands for."""
    inner = match.group(1)
    if "'" in inner or "’" in inner:
        return "'"
    if "-" in inner:
        return "-"
    return " "


def humanize(pattern: str) -> str:
    """A `SPOKEN_TO_SYMBOL` regex → the phrase a human would say.

    Handles the constructs the table actually uses: `(?:a|b)` → "a/b", char
    classes → their readable char, optional `?` dropped (the char stays). A
    result still holding regex metacharacters means a new construct slipped in
    — `test_cheatsheet` guards exactly that, so this can't silently mangle.
    """
    s = re.sub(r"\(\?:([^)]*)\)", lambda m: m.group(1).replace("|", "/"), pattern)
    s = re.sub(r"\[([^\]]*)\]", _class_repl, s)
    s = s.replace("?", "")
    return re.sub(r"\s+", " ", s).strip()


_SYMBOL_LABEL = {"\n": "↵ (nouvelle ligne)", "\n\n": "¶ (paragraphe)"}


def _punctuation_entries() -> list[CheatEntry]:
    by_symbol: dict[str, list[str]] = {}
    for pattern, symbol in punctuation.SPOKEN_TO_SYMBOL:
        by_symbol.setdefault(symbol, []).append(humanize(pattern))
    return [
        CheatEntry(
            category="Ponctuation",
            title=_SYMBOL_LABEL.get(symbol, symbol),
            triggers=tuple(phrases),
            note="Dis le mot, obtiens le symbole (FR+EN). Conservateur : les "
            "tournures courantes (« point de vue ») restent du texte.",
        )
        for symbol, phrases in by_symbol.items()
    ]


# --- commands -----------------------------------------------------------------


def _command_entries() -> list[CheatEntry]:
    v = commands.vocabulary()
    # canonical units (word/char/line/all) — say them in FR or EN (mot, lettre,
    # ligne, tout / word, char, line, everything); the grammar accepts both.
    units = ", ".join(v["units"])
    return [
        CheatEntry(
            "Commandes",
            "Effacer",
            tuple(v["delete_triggers"]),
            f"DOUBLE le mot pour activer (« efface efface ») — l'interlock "
            f"anti-prose. Unités : {units}. Ex : « delete delete deux mots ».",
        ),
        CheatEntry(
            "Commandes",
            "Annuler",
            tuple(v["undo"]),
            "Annule la dernière action — réversible, donc aucun doublage requis.",
        ),
        CheatEntry(
            "Commandes",
            "Ajuster",
            tuple(v["nudge_more"] + v["nudge_less"]),
            "Ajuste la dernière édition d'un cran (plus / moins).",
        ),
        CheatEntry(
            "Commandes",
            "Terminal",
            tuple(v["open_terminal"]),
            "Ouvre un terminal.",
        ),
        CheatEntry(
            "Commandes",
            "Forcer le texte",
            tuple(f"{p} …" for p in v["literal_prefixes"]),
            "Échappement littéral : dicte la suite telle quelle, même si elle "
            "ressemble à une commande (« dis efface efface » écrit le texte).",
        ),
    ]


# --- syntax families (each carries its own help) ------------------------------


def _syntax_entries() -> list[CheatEntry]:
    return [
        CheatEntry("Syntaxe", feat.name, feat.triggers, feat.summary)
        for feat in syntax.catalogue()
    ]


# --- public API ---------------------------------------------------------------


def _quickchat_entries() -> list[CheatEntry]:
    """The live quick-chat macros (#89) — your personal pack AND the built-in
    role pack (#90), so a macro you defined OR one your role activated is
    discoverable, not a secret you have to remember. Empty → no section."""
    if not settings.get("quickchat_enabled"):
        return []
    out: list[CheatEntry] = []
    for phrase in quickchat.active_phrases():
        preview = " ".join(phrase.expansion.split())
        if len(preview) > 60:
            preview = preview[:59] + "…"
        out.append(CheatEntry("Quick-chat", phrase.trigger, (), f"→ {preview}"))
    return out


def entries() -> list[CheatEntry]:
    """The whole sheet, in display order: commands, punctuation, syntax, and any
    quick-chat macros the user has defined."""
    return [
        *_command_entries(),
        *_punctuation_entries(),
        *_syntax_entries(),
        *_quickchat_entries(),
    ]


def _fold(text: str) -> str:
    """Casefold + strip accents, so « éCRIS » matches "ecris"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def search(query: str, items: list[CheatEntry] | None = None) -> list[CheatEntry]:
    """Entries whose text contains `query`, accent- and case-insensitively.
    Empty query returns everything (the searchable panel's default view)."""
    items = entries() if items is None else items
    needle = _fold(query).strip()
    if not needle:
        return list(items)
    return [e for e in items if needle in _fold(e.haystack())]


def as_text(query: str = "", *, brief: bool = False) -> str:
    """Render the sheet (optionally filtered) as text. The ONE renderer the CLI,
    spoken-help notification (#85), and any future panel share, so they can't
    show different help. `brief` = one line per row (title + first triggers),
    sized for a desktop notification; full = triggers + notes, for the CLI."""
    items = search(query)
    if not items:
        return f"Rien pour « {query} »." if query else "(vide)"
    lines: list[str] = []
    category: str | None = None
    for entry in items:
        if entry.category != category:
            category = entry.category
            lines.append(category if not lines else f"\n{category}")
        if brief:
            lines.append(f"  {entry.title} : {', '.join(entry.triggers[:2])}")
            continue
        lines.append(f"  {entry.title}")
        lines.extend(f"      · {trigger}" for trigger in entry.triggers)
        if entry.note:
            lines.append(f"      {entry.note}")
    return "\n".join(lines)
