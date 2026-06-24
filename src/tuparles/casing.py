"""Re-case engine — match the user's natural capitalization style (EPIC #119).

This is *descriptive* casing: take the near-final text and re-case it to the
style the user actually writes in (all-lowercase "lowkey", Sentence case, …).
That is the opposite of the prescriptive voice-caps syntax family (#59), which
*adds* capitals on a spoken command. They will eventually need to compose:
running casing last would down-case exactly the word #59 just capitalized under
a `lower` style. That conflict is **latent, not live** — no UI writes
`casing_style`, so non-`preserve` styles are unreachable today, and #59 ships
standalone. The fix is deferred to #121 (the style-inference work that first
makes a non-preserve style reachable): the per-token `protect` predicate can't
carry the *positional* fact "this particular capital was explicit", so #121
will pick the right channel then (a deliver-verbatim sentinel, a stage reorder,
or a per-feature case-stability flag) rather than guess now.

DOCTRINE (inherited from #41, #53): a wrong autocorrect is worse than a visible
mishear. So:

  * The default style is ``preserve`` — pure identity. The engine ships dark;
    nothing re-cases until the user opts into a style in Réglages. "It's a
    setting": smart default + total override.
  * Even once a style is on, we never touch tokens that are *obviously not
    prose*: URLs, emails, @handles, #tags, file paths, identifiers
    (camelCase, snake_case, anything with a digit), and ALL-CAPS acronyms
    (len >= 2). These are orthographic, model-free guards — they belong to the
    engine. *Proper-noun* protection (Marie, Paris) needs NLP and is #122; it
    plugs in through the ``protect`` predicate, which the engine ships without.

HONEST LIMITS until #122/#116 land:
  * ``lower`` lowercases proper nouns: "i met marie in paris". That IS the
    lowkey aesthetic, so it's defensible as an opt-in — but it's a known gap,
    not a polished result. Same for plural acronyms ("APIs" -> "apis", "IDs" ->
    "ids"): ``str.isupper()`` is False on them, so the acronym guard misses
    them. Fine for an opt-in all-lowercase style; documented so it doesn't read
    as a bug.
  * ``protect`` is a per-*token* predicate. Contextual NER (#122) may need the
    surrounding sentence to disambiguate ("Marché" the market vs a surname); a
    future seam may have to be span-based. Kept simple deliberately.

All transforms use Python's unicode-correct ``str.lower/upper`` and per-char
``str.isupper/islower/isalpha`` — never an ``a-z``/``à-ÿ`` regex range, which
silently drops œ/Œ, æ/Æ and friends past U+00FF. This is a French tool; the
ligatures matter.
"""

from __future__ import annotations

import re
import string
from collections.abc import Callable

from tuparles import settings

# The styles we know how to render. Anything else -> preserve (conservative).
STYLES: tuple[str, ...] = ("preserve", "lower", "sentence", "upper")

# Punctuation stripped to find a token's alphabetic "core" (for the acronym
# test). string.punctuation is ASCII-only, so add the French/typographic marks.
_PUNCT = string.punctuation + "«»…“”‘’–—"

_SPLIT = re.compile(r"(\s+)")  # keep the whitespace runs so we can rejoin exactly


def _has_internal_caps(token: str) -> bool:
    """True for camelCase / PascalCase mid-word capitals (iPhone, GitHub).
    An uppercase letter following a lowercase one — the structural signal that
    this is an identifier or brand, not prose. "Hello" is NOT caught (the H
    leads); "HelloWorld" and "iOS" are."""
    prev_lower = False
    for ch in token:
        if prev_lower and ch.isupper():
            return True
        prev_lower = ch.islower()
    return False


def _is_protected(token: str, protect: Callable[[str], bool] | None) -> bool:
    """Should this token be left exactly as dictated? The conservative guard.

    Orthographic, model-free: structured tokens (URL/email/handle/path/
    identifier), digit-bearing tokens, mixed-case brands, and ALL-CAPS acronyms.
    The optional ``protect`` predicate adds caller-supplied spans (#122 proper
    nouns, #116 gazetteer) on top. Single letters fall through on purpose, so a
    lowkey-lowercase user still gets "i"."""
    if not token:
        return True
    if "://" in token or any(c in token for c in "@/\\_"):
        return True
    if any(c.isdigit() for c in token):
        return True
    if _has_internal_caps(token):
        return True
    core = token.strip(_PUNCT)
    if len(core) >= 2 and core.isupper():  # API, NASA, ÉTAT
        return True
    return bool(protect and core and protect(core))  # caller spans (#122/#116)


def _upcase_first_alpha(token: str) -> str:
    """Uppercase the first alphabetic char, leave the rest untouched. Handles a
    leading bracket/quote ("(hello" -> "(Hello") and never down-cases the tail
    (so "iPhone" would stay — though such tokens are protected before we ever
    get here)."""
    for i, ch in enumerate(token):
        if ch.isalpha():
            return token[:i] + ch.upper() + token[i + 1 :]
    return token


def _map_tokens(
    text: str, transform: Callable[[str], str], protect: Callable[[str], bool] | None
) -> str:
    """Apply ``transform`` to every prose token, preserving protected tokens and
    all whitespace verbatim. Used for ``lower`` and ``upper``."""
    out = []
    for part in _SPLIT.split(text):
        if not part or part.isspace() or _is_protected(part, protect):
            out.append(part)
        else:
            out.append(transform(part))
    return "".join(out)


def _sentence_case(text: str, protect: Callable[[str], bool] | None) -> str:
    """Capitalize the first letter of each sentence; never down-case anything.

    Up-casing-only is what makes this safe: it can't destroy a mid-sentence
    proper noun or acronym (the worst it does is capitalize a word that already
    starts a sentence, which is correct). Sentence start = text start or after a
    token whose *raw last character* is ``. ! ?``.

    Deliberately conservative on two fronts, per "when in doubt, it's text":
      * A terminator hidden behind a closing quote/bracket ('he said "go."')
        does NOT start a new sentence — so we never capitalize "then" on an
        ambiguous quote-internal period. The cost is a missed capital after a
        sentence that ends on a closing mark; a missed cosmetic beats a wrong
        rewrite of the user's prose.
      * An abbreviation ("U.S.A.") still reads as a terminator — an accepted
        best-effort imperfection."""
    out = []
    cap_next = True
    for part in _SPLIT.split(text):
        if not part or part.isspace():
            out.append(part)
            continue
        token = part
        if cap_next and not _is_protected(token, protect):
            token = _upcase_first_alpha(token)
        if any(c.isalpha() for c in token):
            cap_next = False
        if token[-1] in ".!?":
            cap_next = True
        out.append(token)
    return "".join(out)


def recase(
    text: str, style: str = "preserve", *, protect: Callable[[str], bool] | None = None
) -> str:
    """Re-case ``text`` to ``style``. Pure and total: any string in, string out;
    an unknown style is identity (conservative). ``protect(core)`` -> True marks
    a token to leave untouched (the #122/#116 seam)."""
    if not text or style == "preserve":
        return text
    if style == "lower":
        return _map_tokens(text, str.lower, protect)
    if style == "upper":
        return _map_tokens(text, str.upper, protect)
    if style == "sentence":
        return _sentence_case(text, protect)
    return text


def active_style() -> str:
    """The user's chosen casing style, validated. Unknown/absent -> preserve."""
    style = settings.get("casing_style")
    return style if style in STYLES else "preserve"


def apply_casing(text: str, protect: Callable[[str], bool] | None = None) -> str:
    """Re-case using the active setting — the one call the pipeline makes.
    Default ``preserve`` makes this an identity until the user opts in."""
    return recase(text, active_style(), protect=protect)
