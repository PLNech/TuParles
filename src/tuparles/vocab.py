"""Personal glossary tooling: mine your own dictation history for the
names and jargon worth biasing the decoder toward.

The doctrine (see CONTRIBUTING.md) applies here too: suggestions only,
the human approves every word. A glossary that grows on its own would
slowly become an autocorrect — and a wrong autocorrect is worse than a
visible mishear.
"""

import re
from pathlib import Path

from tuparles.config import VOCAB_FILE

# Tokens worth a glossary slot regardless of frequency context:
# snake_case, digits-in-word (large-v3), camelCase, ALLCAPS acronyms.
_TECHNICAL = re.compile(
    r"_|\d"
    r"|[a-z][A-Z]"  # camelCase / PascalCase
    r"|^[A-Z]{2,8}$"  # KPI, GPU, DIPI
)
_SENTENCE_END = re.compile(r"[.?!…:]\s*$")
_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][\w'-]*", re.UNICODE)


def load(path: Path = VOCAB_FILE) -> list[str]:
    """Glossary words, comments and blanks stripped, file order kept."""
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def add(words: list[str], path: Path = VOCAB_FILE) -> list[str]:
    """Append new words (case-insensitive dedup); returns what was added."""
    known = {w.casefold() for w in load(path)}
    fresh = []
    for w in words:
        w = w.strip()
        if w and w.casefold() not in known:
            fresh.append(w)
            known.add(w.casefold())
    if fresh:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        path.write_text(existing + "\n".join(fresh) + "\n", encoding="utf-8")
    return fresh


def suggest(
    texts: list[str],
    existing: set[str] | None = None,
    min_count: int = 2,
) -> list[tuple[str, int]]:
    """Candidate glossary words from past takes, most frequent first.

    Two families: *technical* tokens (snake_case, camelCase, digits,
    acronyms) and *proper nouns* (Capitalized mid-sentence — sentence
    starts don't count, anything is capitalized there).
    """
    known = {w.casefold() for w in existing or set()}
    counts: dict[str, int] = {}
    casing: dict[str, str] = {}  # most recently seen original casing
    for text in texts:
        for match in _WORD.finditer(text):
            token = match.group()
            folded = token.casefold()
            if folded in known or len(token) < 2:
                continue
            if _TECHNICAL.search(token):
                keep = True  # technical: every occurrence counts
            elif token[0].isupper() and token[1:].islower() and len(token) > 2:
                # Proper noun only mid-sentence — anything is capitalized
                # right after an opening or a period.
                prefix = text[: match.start()].strip()
                keep = bool(prefix) and not _SENTENCE_END.search(prefix)
            else:
                keep = False
            if not keep:
                continue
            counts[folded] = counts.get(folded, 0) + 1
            casing[folded] = token
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(casing[w], n) for w, n in ranked if n >= min_count]
