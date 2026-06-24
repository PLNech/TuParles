"""Spoken capitalization — region all-caps (#59, EPIC #53).

Wrap a passage you want SHOUTED between a paired open/close, bilingually:

  FR : "tout en majuscules" … "fin des majuscules"
  EN : "all caps" … "end caps"

and the span between is upper-cased, the trigger words removed. This is
*prescriptive* casing (you command it), the mirror of the *descriptive* re-case
engine (`casing.py`, #120) that matches your habitual style. Inside an explicit
all-caps region we upper-case everything — you asked for it — so unlike #120
there is no identifier/acronym guard here.

SAFETY (the doctrine, made structural — [[feedback-structural-command-disambiguation]]):
"majuscules" / "caps" are ordinary words, so the interlock is **require the
close**. A region fires only as a complete open…close PAIR; a lone "tout en
majuscules" with no closing phrase stays literal text. This is deliberately
*more* conservative than quotes' auto-close-at-take-end: an unclosed quote only
adds one mark, but an unclosed caps-open auto-closing to the take end would
SHOUT the entire rest of the take — squarely the wrong-autocorrect side of the
asymmetry. When in doubt, it's text. The misfire corpus (`test_caps.py`) is the
load-bearing test: prose like "je l'ai écrit en majuscule" must never fire.

NOT here: next-word capitalize ("majuscule <mot>") — bare "majuscule"/"capital"
has no safe trigger without the held-modifier quasimode (#62); and "smart
proper-nouns" is *descriptive*, so it belongs to smart-lowercase (#122). #59
ships the region third only; the rest is tracked separately.
"""

from __future__ import annotations

import re

from tuparles import syntax

# Distinctive multi-word phrases, longest-first. Requiring the matching close
# (below) is the structural interlock; these never fire alone.
_OPEN = r"tout\s+en\s+majuscules|en\s+majuscules|all\s+caps(?:\s+on)?"
# Close phrases. Beyond the explicit "fin des majuscules" / "end caps", a
# switch to the *other* mode also closes: "en minuscules" / bare "minuscule(s)"
# / "lowercase" (a one-way synonym — saying lowercase ends the shout). This is
# safe ONLY because of require-close: a lone "minuscule" in prose has no open to
# pair with, so it stays inert. ("en minuscules" before bare so it eats the
# "en".) The general dual-mode engine — where each mode's open is the other's
# close, with a force-lowercase region too — is #59's richer follow-up; it needs
# a mode register and a harder collision analysis (minuscule/majuscule are very
# common), so it is deliberately not done here.
_CLOSE = (
    r"fin\s+(?:de\s+|des\s+)?majuscules|end\s+caps|caps\s+off|"
    r"en\s+minuscules?|minuscules?|lower\s*case"
)

# OPEN … (span) … CLOSE, non-greedy so the nearest close pairs. A lone OPEN with
# no following CLOSE simply doesn't match -> stays text. DOTALL so a region can
# span newlines.
_REGION = re.compile(
    rf"\b(?:{_OPEN})\b\s*(.*?)\s*\b(?:{_CLOSE})\b",
    re.IGNORECASE | re.DOTALL,
)


def apply(text: str, ctx: syntax.SyntaxContext) -> str:
    # Explicit command: upper-case the whole span (unicode-correct), drop the
    # trigger words. No guard — the user asked for all caps.
    return _REGION.sub(lambda m: m.group(1).upper(), text)


syntax.register(
    syntax.SyntaxFeature(
        name="caps",
        apply=apply,
        order=35,  # after quotes (30); both are span rewrites, order is cosmetic
        summary="Encadre un passage à crier : « tout en majuscules … fin des "
        "majuscules ». Sans la fermeture, ça reste du texte.",
        triggers=(
            "tout en majuscules … fin des majuscules",
            "all caps … end caps",
        ),
    )
)
