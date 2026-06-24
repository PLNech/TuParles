"""Normalization for denylist matching ONLY.

Casefold + strip accents (NFKD) + de-leet, so "Ascensio", "ascensio", and
"4sc3nsio" all match one denylist entry. This is used only to *decide whether*
to redact a token - never on text that gets delivered, so it can be lossy.
"""

from __future__ import annotations

import unicodedata

# Conservative leet map - only unambiguous substitutions (no "l"->"1" both ways).
_LEET = str.maketrans(
    {"@": "a", "4": "a", "0": "o", "3": "e", "1": "i", "$": "s", "5": "s", "7": "t"}
)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().translate(_LEET)
