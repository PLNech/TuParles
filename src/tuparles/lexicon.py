"""Personal lexicon: deterministic fixes for recurring ASR mishears.

Whisper's beam search hands us a single hypothesis — by the time text
reaches this layer the acoustics are gone, so nothing here "corrects"
speech. It only rewrites mishears we've caught red-handed more than
once, where the fix is unambiguous. When in doubt, leave it out: a
wrong auto-correction is worse than a visible mishear.
"""

import re

# pattern (matched case-insensitively) → canonical replacement
LEXICON: dict[str, str] = {
    r"\bqlors\b": "alors",
    r"\b[bp]oule request\b": "pull request",
    r"\bau fil ligne\b": "au feeling",
}


def apply_lexicon(text: str) -> str:
    for pattern, replacement in LEXICON.items():

        def _sub(m: re.Match[str], rep: str = replacement) -> str:
            return _match_case(rep, m.group(0))

        text = re.sub(pattern, _sub, text, flags=re.IGNORECASE)
    return text


def _match_case(replacement: str, source: str) -> str:
    """Follow the case of what we replace: 'Qlors'→'Alors', 'qlors'→'alors'."""
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement
