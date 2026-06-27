"""The token-stream model: a take's text as a list of `Span`, not a flat string.

Why a type (#21): the product doctrine — *a wrong autocorrect is worse than a
visible mishear* — is only half-built. We refuse to silently fix, but we also
can't visibly *flag*: the UI sees one opaque string, so it can't dim the word the
decoder was unsure of, or reveal that "Claude" started life as "cloud". A flat
string has no room for "how sure?" or "what was this before?". A list of spans
does.

Each `Span` is one token (a word, a punctuation run, a stretch of spaces, a
newline) carrying:
- `confidence` — None/1.0 = certain; lower = the decoder hedged (render dimmer).
- `origin` — where this surface came from: decoded as-is, inserted by a rule,
  rewritten from something else, re-cased, or left by repeat-collapse.
- `original` — the pre-rewrite surface, kept so a rewrite can be *revealed*, never
  hidden (#26): we change your words only out loud.

THE INVARIANT that keeps this safe: `flatten(tokenize(t)) == t`, byte for byte.
The span layer is a lossless re-view of the text, never a second source of truth —
so delivery and storage (which flatten back to a string) are untouched by it. The
span-aware pipeline (#22) must preserve the same equality against `postprocess`.

Pure + headless: no Qt, no engine, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Kind = Literal["word", "punct", "space", "newline"]
Origin = Literal["decoded", "inserted", "rewritten", "cased", "collapsed"]


@dataclass(frozen=True)
class Span:
    """One token of a take. `text` is the surface that flattens back into the
    delivered string; the rest is metadata the UI may render but delivery ignores."""

    text: str
    kind: Kind
    confidence: float | None = None  # None or >=1.0 ⇒ certain
    origin: Origin = "decoded"
    original: str | None = None  # pre-rewrite surface, if this was changed

    @property
    def certain(self) -> bool:
        """Whether to render this at full brightness — no hedge to show."""
        return self.confidence is None or self.confidence >= 1.0

    @property
    def rewritten(self) -> bool:
        """True when the surface differs from what was originally there — the
        cue for X→Y reveal (#26). `original is None` means 'untouched', NOT
        'rewritten to empty'."""
        return self.original is not None and self.original != self.text


def flatten(spans: Iterable[Span]) -> str:
    """The spans back into the exact string for delivery + storage. The span
    layer is a view; this is how you leave it. `flatten(tokenize(t)) == t`."""
    return "".join(s.text for s in spans)


# One pass that partitions ANY string with zero loss, in order: a newline, then a
# run of other whitespace, then a run of word chars (Unicode \w covers accents),
# then a run of everything else (punctuation/symbols). The four alternatives are
# disjoint and exhaustive (\n ∪ rest-of-\s ∪ \w ∪ not-\w-not-\s = every char), so
# joining the matches reproduces the input byte for byte — the invariant.
_TOKEN = re.compile(r"\n|[^\S\n]+|\w+|[^\w\s]+", re.UNICODE)


def _kind(token: str) -> Kind:
    if token == "\n":
        return "newline"
    if token.isspace():
        return "space"
    if token[0].isalnum() or token[0] == "_":  # \w+ matched: a word
        return "word"
    return "punct"


def tokenize(text: str, confidence: float | None = None) -> list[Span]:
    """A decoded string → its spans, every token tagged `origin="decoded"`. The
    canonical builder for a fresh take's text. `confidence`, if given, is applied
    to WORD spans only (punctuation/space/newline are always certain); per-word
    confidences are layered on later (#16/#23). Round-trips: `flatten` undoes it."""
    spans: list[Span] = []
    for m in _TOKEN.finditer(text):
        tok = m.group()
        kind = _kind(tok)
        conf = confidence if kind == "word" else None
        spans.append(Span(tok, kind, confidence=conf, origin="decoded"))
    return spans
