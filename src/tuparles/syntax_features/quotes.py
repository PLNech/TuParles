"""Spoken quotes — the first structured-dictation family (#32, EPIC #53).

Say the quote out loud and get real quote marks, bilingually, with the pairing
handled for you. Triggers (all settings-gated as one feature for now):

  FR open  : "ouvre/ouvrez/ouvrir les guillemets", "guillemets ouvrants",
             "entre guillemets" (wrap-the-phrase opener)
  FR close : "ferme/fermez/fermer les guillemets", "guillemets fermants"
  FR bare  : "guillemets" alone — auto-alternates open/close
  EN open  : "open quote(s)" / "opening quote(s)"
  EN close : "close/closing quote(s)", "end quote(s)", "unquote"
  + auto-close: if you open and never close, we close it at the end of the take.

SAFETY (the doctrine, made structural): bare "guillemets" is the only
collision-prone trigger — it's also an ordinary French word. So a LONE bare
"guillemets" is left as text; it's only treated as quotes when it appears in a
PAIR (≥2 in the take). Mentioning "les guillemets" in a sentence stays
untouched; deliberately voicing a quoted phrase uses two. Explicit triggers are
unambiguous and always honoured. When in doubt, it's text.

MARKS are a setting (smart default + total override — settings["quotes"]):
  fr: "straight" (default) | "guillemets-narrow" | "guillemets-full" |
      "guillemets-none"
  en: "straight" (default) | "curly" | "context"   (context = curly in prose,
      straight in a code/terminal window once the output-format engine #58
      reports it)
Default is straight " for both languages: tech-friendly, pastes anywhere, never
breaks code. Flip to guillemets/curly per taste.
"""

from __future__ import annotations

import re

from tuparles import settings, syntax

# Longest/explicit branches first so "ouvre les guillemets" wins over bare
# "guillemets"; bare French "guillemets" is the last French alternative.
_TRIGGER = re.compile(
    r"\b(?:"
    r"guillemets\s+ouvrants?|ouvr\w*\s+(?:les\s+)?guillemets|entre\s+guillemets|"
    r"guillemets\s+fermants?|ferm\w*\s+(?:les\s+)?guillemets|"
    r"open(?:ing)?\s+quotes?|"
    r"clos\w*\s+quotes?|end\s+quotes?|unquote|"
    r"guillemets"
    r")\b",
    re.IGNORECASE,
)

# Sentinels carry the language to the glyph-substitution pass; \x00 can't occur
# in dictated text.
_OPEN = "\x00qo{}\x00"
_CLOSE = "\x00qc{}\x00"

_STRAIGHT = ('"', '"', "")
_CURLY = ("“", "”", "")
_GUILLEMET_SPACING = {"narrow": " ", "full": " ", "none": ""}

# Window classes where curly quotes would corrupt syntax → use straight.
_CODEISH = ("term", "konsole", "kitty", "alacritty", "xterm", "code", "kgx", "console")


def _classify(s: str) -> tuple[str, str]:
    """Matched trigger → (lang, kind) with kind in {open, close, bare}."""
    low = s.lower()
    if "quote" in low:  # English (incl. "unquote")
        return ("en", "open" if "open" in low else "close")
    if "ouvr" in low or "entre" in low:
        return ("fr", "open")
    if "ferm" in low:
        return ("fr", "close")
    return ("fr", "bare")


def _config() -> dict:
    cfg = settings.get("quotes")
    return cfg if isinstance(cfg, dict) else {}


def _marks(lang: str, ctx: syntax.SyntaxContext) -> tuple[str, str, str]:
    cfg = _config()
    style = cfg.get(lang, "straight")  # straight ", both languages, by default
    if style == "curly":
        return _CURLY
    if style.startswith("guillemets"):
        spacing = style.partition("-")[2] or "narrow"
        inner = _GUILLEMET_SPACING.get(spacing, " ")
        return ("«", "»", inner)
    if style == "context":  # EN smart: straight in code, curly in prose
        app = (ctx.app_class or "").lower()
        return _STRAIGHT if any(k in app for k in _CODEISH) else _CURLY
    return _STRAIGHT


def apply(text: str, ctx: syntax.SyntaxContext) -> str:
    matches = list(_TRIGGER.finditer(text))
    if not matches:
        return text

    # Structural guard: a lone bare "guillemets" is the word, not a quote.
    bare_count = sum(1 for m in matches if _classify(m.group(0))[1] == "bare")
    treat_bare = bare_count >= 2

    out: list[str] = []
    stack: list[str] = []
    last = 0
    for m in matches:
        lang, kind = _classify(m.group(0))
        if kind == "bare":
            if not treat_bare:
                continue  # leave the literal word in place
            kind = "close" if stack else "open"
        out.append(text[last : m.start()])
        if kind == "open":
            stack.append(lang)
            out.append(_OPEN.format(lang))
        else:
            if stack:
                stack.pop()
            out.append(_CLOSE.format(lang))
        last = m.end()
    out.append(text[last:])
    text = "".join(out)

    if stack and _config().get("auto_close", True):
        text += "".join(_CLOSE.format(lang) for lang in reversed(stack))

    # Hug: drop spaces the trigger words left behind, just inside the marks.
    text = re.sub(r"(\x00qo(?:fr|en)\x00)[ \t]+", r"\1", text)
    text = re.sub(r"[ \t]+(\x00qc(?:fr|en)\x00)", r"\1", text)

    for lang in ("fr", "en"):
        open_g, close_g, inner = _marks(lang, ctx)
        text = text.replace(_OPEN.format(lang), open_g + inner)
        text = text.replace(_CLOSE.format(lang), inner + close_g)
    return text


syntax.register(syntax.SyntaxFeature(name="quotes", apply=apply, order=30))
