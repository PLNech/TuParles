"""Quick-chat / voice macros (#89, EPIC #88): a SHORT spoken trigger → a curated
expansion, instantly. The inverse of free dictation — CS-radio "enemy spotted"
meets Dragon's medical auto-texts.

Safety is structural, exactly as for spoken commands (#41): a trigger only fires
on an ANCHORED whole-take match (`fullmatch`), never a fuzzy score and never a
substring inside prose. Say *exactly* the trigger (plus any template tail) and
it expands; say a sentence that merely contains the trigger words and it stays
text. When in doubt, it's text.

Everything is a setting: the pack is a hand-editable JSON file in XDG config,
re-read every take (hot-reload like vocab/lexicon). An empty/absent pack is a
silent no-op, so the feature is safe-on by default — it can't fire until you
write a macro. Role packs (#90) and richer activation (#91) build on this core.

Pure and dependency-free: `expand(text, phrases)` is the whole engine; the file
and settings layer is thin glue around it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tuparles import settings

# Edge punctuation the decode/punctuation pass may glue on ("lgtm." → "lgtm").
_EDGE = " \t\n.,;:!?…\"'»«“”’"
_SLOT = re.compile(r"<([a-zA-Z_]\w*)>")


@dataclass(frozen=True)
class Phrase:
    """One macro: an anchored `trigger` (may carry `<name>` template slots) and
    the `expansion` it emits. `role`/`lang` are optional tags for pack curation
    (#90) and never affect matching."""

    trigger: str
    expansion: str
    role: str = ""
    lang: str = ""


def _clean(text: str) -> str:
    """Collapse whitespace and strip edge punctuation — the form matched against
    (never delivered). Mirrors the command layer's normalization intent."""
    return re.sub(r"\s+", " ", text).strip().strip(_EDGE).strip()


@lru_cache(maxsize=512)
def _compiled(trigger: str) -> re.Pattern[str]:
    """Trigger → an anchored, case-insensitive regex. `<name>` becomes a
    non-greedy named group; literal parts are escaped. Whitespace-normalized
    triggers match whitespace-normalized takes, so spacing can't break a match.
    """
    parts: list[str] = []
    last = 0
    for slot in _SLOT.finditer(trigger):
        parts.append(re.escape(trigger[last : slot.start()]))
        parts.append(f"(?P<{slot.group(1)}>.+?)")
        last = slot.end()
    parts.append(re.escape(trigger[last:]))
    return re.compile(rf"^{''.join(parts)}$", re.IGNORECASE)


def _fill(expansion: str, values: dict[str, str]) -> str:
    """Substitute captured `<name>` slots into the expansion; unknown slots are
    left verbatim (a typo in the pack shows itself, doesn't silently vanish)."""
    if not values:
        return expansion

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        return values[name].strip() if name in values else match.group(0)

    return _SLOT.sub(repl, expansion)


def expand(text: str, phrases: list[Phrase]) -> str | None:
    """If `text` (a whole take) anchors-matches a phrase trigger, return its
    expansion (template slots filled); otherwise None — it's ordinary text.
    First matching phrase wins (pack order is the tie-break, so put the specific
    before the general)."""
    cleaned = _clean(text)
    if not cleaned:
        return None
    for phrase in phrases:
        match = _compiled(phrase.trigger).fullmatch(cleaned)
        if match:
            return _fill(phrase.expansion, match.groupdict())
    return None


def parse_pack(data: str | dict) -> list[Phrase]:
    """A JSON pack (`{"phrases": [{"trigger","expansion","role"?,"lang"?}]}`) →
    Phrases. Entries missing a trigger or expansion are skipped, not fatal —
    one bad row mustn't void the whole pack."""
    obj = json.loads(data) if isinstance(data, str) else data
    phrases: list[Phrase] = []
    for item in obj.get("phrases", []) if isinstance(obj, dict) else []:
        trigger = re.sub(r"\s+", " ", str(item.get("trigger", ""))).strip()
        expansion = str(item.get("expansion", ""))
        if not trigger or not expansion:
            continue
        phrases.append(
            Phrase(
                trigger=trigger,
                expansion=expansion,
                role=str(item.get("role", "")),
                lang=str(item.get("lang", "")),
            )
        )
    return phrases


def _path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "tuparles" / "phrasepack.json"


def load(path: Path | None = None) -> list[Phrase]:
    """Load the user's pack; [] if absent or malformed (a broken file must never
    cost a take). Read fresh on each call, so edits take effect next take."""
    path = _path() if path is None else path
    try:
        return parse_pack(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def active_phrases() -> list[Phrase]:
    """The live phrase set: the user's personal pack FIRST, then the built-in
    pack for the current role (#90). Personal triggers win on collision (first
    match wins in `expand`), so a role pack is a seed the user can always
    override. Role 'none'/unset contributes nothing. Lazy import keeps
    `quickchat` the dependency-free engine and `rolepacks` the data on top."""
    from tuparles import rolepacks

    return load() + rolepacks.pack_for(settings.get("role"))


def expand_active(text: str) -> str | None:
    """The daemon entry point: expand against the live phrase set (personal +
    role pack), gated on the setting. Empty set → None, so 'enabled' is safe as
    the default."""
    if not settings.get("quickchat_enabled"):
        return None
    return expand(text, active_phrases())
