"""Spoken-punctuation mapping, bilingual Fr/En.

Deterministic escape hatch: when prosody fails the model, the speaker says
"virgule" or "comma" and gets the symbol. Conservative by design — protected
phrases ("point de vue", "à quel point") are shielded before mapping so
everyday speech survives untouched.
"""

import re

# Phrases where a trigger word is ordinary vocabulary, not dictated
# punctuation. Checked (and shielded) before any mapping applies.
PROTECTED_PHRASES = [
    "point de vue",
    "à quel point",
    "au point",
    "sur le point",
    "point commun",
    "point faible",
    "point fort",
    "mise au point",
    "point d'étape",
    "rond-point",
    "deux points de",  # "deux points de vente" etc.
]

# Bare "point" must map for French dictation ("c'est fini point") but is
# everyday English vocabulary. A dictated "point" stands alone at a clause
# boundary; English usage hugs neighbors — a determiner or compound noun
# before, or "of" after. Shield those contexts, map the rest.
PROTECTED_PATTERNS = [
    r"\b(?:floating|breaking?|pain|entry|data|bullet|talking|turning"
    r"|starting|tipping|selling|focal|the|a|an|my|your|his|her|our|their"
    r"|this|that|each|every|no|key|main|whole|good|fair|valid|moot)"
    r"[ ]point(?:s|ers?)?\b",
    r"\bpoints?[ ]of\b",
    # "les/des/ces… trois petits points" is talking ABOUT the ellipsis, not
    # dictating one — shield it so only a bare "trois petits points" maps to …
    # (#7). When in doubt, it's text: a determiner before it means a mention.
    r"\b(?:les|des|ces|aux|mes|tes|ses|nos|vos|leurs|de|du)[ ]"
    r"trois[ ]petits[ ]points\b",
]

# Longest patterns first: "point d'interrogation" must win over "point".
# English "point" is intentionally NOT a trigger (floating point, point of
# view) — English speakers say "period" or "full stop".
SPOKEN_TO_SYMBOL = [
    (r"point d['’]interrogation", "?"),
    (r"point d['’]exclamation", "!"),
    (r"question mark", "?"),
    (r"exclamation (?:mark|point)", "!"),
    (r"trois petits points", "…"),
    (r"points? de suspension", "…"),
    (r"dot dot dot", "…"),
    (r"point[- ]virgule", ";"),
    (r"semicolon", ";"),
    (r"deux points", ":"),
    (r"colon", ":"),
    (r"nouvelle ligne", "\n"),
    (r"à la ligne", "\n"),
    (r"new ?line", "\n"),
    (r"line break", "\n"),
    (r"nouveau paragraphe", "\n\n"),
    (r"new paragraph", "\n\n"),
    (r"virgule", ","),
    (r"comma", ","),
    (r"full stop", "."),
    (r"period", "."),
    (r"point", "."),
]

_SHIELD = "\x00{}\x00"

_PROTECTED_RES = [
    re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in PROTECTED_PHRASES
] + [re.compile(p, re.IGNORECASE) for p in PROTECTED_PATTERNS]
# Triggers may arrive from ASR with trailing punctuation already attached
# ("virgule," when the model heard the prosody too) — absorb it.
_SPOKEN_RES = [
    (re.compile(rf"\b{pat}\b[.,]?", re.IGNORECASE), sym)
    for pat, sym in SPOKEN_TO_SYMBOL
]


def apply_spoken_punctuation(text: str) -> str:
    """Replace dictated punctuation words with symbols, then tidy spacing."""
    shielded: list[str] = []

    def _shield(match: re.Match) -> str:
        shielded.append(match.group(0))
        return _SHIELD.format(len(shielded) - 1)

    for pattern in _PROTECTED_RES:
        text = pattern.sub(_shield, text)

    for pattern, symbol in _SPOKEN_RES:
        text = pattern.sub(symbol, text)

    for i, original in enumerate(shielded):
        text = text.replace(_SHIELD.format(i), original)

    return _tidy(text)


def _tidy(text: str) -> str:
    """Fix spacing around inserted symbols and recapitalize sentences."""
    text = re.sub(r"[ \t]+([,.;:?!])", r"\1", text)
    # Collapse a redundant comma: saying "virgule" while Whisper also heard the
    # pause emits a doubled "test, ," ; a comma butting a stronger mark ("poème,
    # .") is swallowed by it. Comma-only and exact — never merge different marks
    # ("?!" stays) and never touch "…"/"..." (no comma involved). (#6)
    text = re.sub(r",(?:[ \t]*,)+", ",", text)  # ", ," / ",," → ","
    text = re.sub(r",[ \t]*(?=[.?!;:])", "", text)  # ", ." → "."
    text = re.sub(r"(?<=[.?!;:])[ \t]*,", "", text)  # ". ," → "."
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    # ASR sometimes glues sentences: "question.Alors" — reopen the gap, but
    # only lowercase→[.?!]→Uppercase so filenames (main.py) and decimals survive
    text = re.sub(r"([a-zà-ÿ][.?!])(?=[A-ZÀ-Ÿ])", r"\1 ", text)
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(
        r"([.?!]\s+|\n+)([a-zà-ÿ])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text
