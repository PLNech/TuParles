"""Spoken slashes — "slash" is a path separator (#53 family).

You dictate INTO Claude Code, a shell, a URL bar, a code comment. All of them
spell `/` the same way you say it: "slash". So the rule is simple and total —
**every spoken "slash" becomes "/"**, gluing to its neighbours the way a real
separator does:

    "slash help"                  → "/help"          (a command)
    "endpoint slash habits"       → "endpoint/habits" (a REST path)
    "code slash slash comment"    → "code//comment"   (a // comment)
    "et slash ou"                 → "et/ou"

This fires ANYWHERE, not just at a line head (the product owner's call: when you
say "slash" you mean the glyph, near enough always — 2026-06-28 take forensics).
Two refinements on top of the bare substitution:

  Ontology canonicalisation — a curated set of Claude Code commands fixes the
    spelling the decoder splits: "slash pré compact" → "/pre-compact",
    "slash code review" → "/code-review". This is the ONE place the slash isn't a
    dumb separator: it joins/hyphenates a known multi-word command name.

  Sentence breaks survive — "/" glues to adjacent word characters, but a "/"
    that lands after sentence punctuation keeps its space ("Bonjour. /help", not
    "Bonjour./help"). The glue is between *words*, where a path lives.

DOCTRINE NOTE. This deliberately relaxes the house "when in doubt, it's text"
asymmetry: a prose "rapport qualité slash prix" becomes "qualité/prix", and that
is accepted because in this user's dictation "slash" is virtually always the
glyph. It stays a setting — `settings["syntax"]["slashes"]` turns the whole
family off — and the decode-time half (so Whisper hears "slash" at all) lives in
`seed_prompt.COMMAND_SEED`, validated to rescue "slash precompact" from decoding
as "c'est l'âge prix compact".

STILL HARD (the roadmap): full URLs spoken fast ("https deux-points slash slash
…") mangle *acoustically* into "https2…/slashnek" before any text rule sees them,
and code constructs (function_names(), :: , -> ) want their own grammar. Those
need the spoken spell/dictation mode ([[url-dictation-mode-followup]]); this
family is the separator, not that mode.

`settings["slash_commands"]` (a flat list) extends the command ontology with your
own — smart default, total override.
"""

from __future__ import annotations

import re
import unicodedata

from tuparles import settings, syntax

# The command ontology: Claude Code built-ins plus the skills a user of THIS repo
# dictates. Canonical (hyphenated) form on the left is what we emit; matching
# ignores spaces/hyphens/case, so "code review" / "code-review" / "codereview"
# all land on "/code-review". Extend per project via settings["slash_commands"].
KNOWN_COMMANDS: tuple[str, ...] = (
    # Claude Code built-ins
    "help",
    "clear",
    "compact",
    "config",
    "cost",
    "init",
    "memory",
    "model",
    "review",
    "status",
    "vim",
    "agents",
    "context",
    "resume",
    "export",
    "login",
    "logout",
    "doctor",
    "bug",
    "mcp",
    "hooks",
    "permissions",
    "ide",
    "add-dir",
    "pr-comments",
    "release-notes",
    "terminal-setup",
    # Skills this repo leans on (the names the user says out loud)
    "pre-compact",
    "session-planning",
    "code-review",
    "security-review",
    "verify",
    "simplify",
    "loop",
    "run",
    "fewer-permission-prompts",
    "keybindings-help",
    "claude-api",
    "deep-research",
    "update-config",
)

# Up to this many spoken words may form one command name ("terminal setup",
# "fewer permission prompts"). Bounds the join search; commands are short.
_MAX_WORDS = 3


def _strip_accents(s: str) -> str:
    """Fold diacritics to ASCII: "pré" → "pre", "dépôt" → "depot". Commands and
    path segments are ASCII; the decoder writes the accent, we trim it."""
    folded = unicodedata.normalize("NFKD", s)
    return "".join(c for c in folded if not unicodedata.combining(c))


def _key(s: str) -> str:
    """Collapse a spoken fragment to its match key: accent-folded, lowercase,
    alphanumerics only. "Pré-Compact.", "pre compact" and "precompact" all →
    "precompact"."""
    return re.sub(r"[^a-z0-9]", "", _strip_accents(s.lower()))


def _ontology() -> dict[str, str]:
    """Match-key → canonical command, base list plus any user extras. Built per
    call so a live settings edit (extras added) takes effect without restart."""
    table = {_key(c): c for c in KNOWN_COMMANDS}
    extra = settings.get("slash_commands")
    if isinstance(extra, list):
        for c in extra:
            if isinstance(c, str) and (k := _key(c)):
                table[k] = c.strip().lstrip("/")
    return table


# "slash" + up to three following word-tokens — the canonicalisation candidate.
_CMD_RE = re.compile(r"\bslash\b[ \t]+((?:[\w'’-]+[ \t]+){0,2}[\w'’-]+)", re.IGNORECASE)
# The bare spoken word, anywhere. \b keeps "backslash"/"slashdot" out of it.
_WORD_RE = re.compile(r"\bslash\b", re.IGNORECASE)


def apply(text: str, ctx: syntax.SyntaxContext) -> str:
    known = _ontology()

    def _cmd_repl(m: re.Match[str]) -> str:
        words = m.group(1).split()
        for k in range(min(len(words), _MAX_WORDS), 0, -1):
            canonical = known.get(_key("".join(words[:k])))
            if canonical:
                rest = " ".join(words[k:])
                return f"/{canonical}" + (f" {rest}" if rest else "")
        return m.group(0)  # not a command → fall through to the bare substitution

    # 1. Canonicalise known commands (the only spelling-aware step).
    text = _CMD_RE.sub(_cmd_repl, text)
    # 2. Every remaining spoken "slash" → "/".
    text = _WORD_RE.sub("/", text)
    # 3. Behave like a separator: collapse "/ /" → "//" (comments, URLs) and glue
    #    "/" to adjacent word chars. A "/" after sentence punctuation keeps its
    #    space — the glue is between words, where a path component lives.
    text = re.sub(r"/[ \t]+/", "//", text)
    text = re.sub(r"(\w)[ \t]+/", r"\1/", text)
    text = re.sub(r"/[ \t]+(?=\w)", "/", text)
    # 4. Whatever follows a "/" is a command or path segment → ASCII. The decoder
    #    writes "pré-compact"; the command is "pre-compact". Trim the accents.
    text = re.sub(
        r"(/)([\w'’-]+)", lambda m: m.group(1) + _strip_accents(m.group(2)), text
    )
    return text


syntax.register(
    syntax.SyntaxFeature(
        name="slashes",
        apply=apply,
        order=20,  # before quotes/caps; runs after spoken punctuation (the stage)
        summary="« slash » devient « / » partout — commandes (« slash compact » → "
        "« /compact »), chemins (« endpoint slash habits » → « endpoint/habits »), "
        "commentaires (« slash slash »). Les commandes connues sont corrigées "
        "(« slash pré compact » → « /pre-compact »).",
        triggers=(
            "slash help → /help",
            "endpoint slash habits → endpoint/habits",
            "slash code review → /code-review",
            "slash slash → //",
        ),
    )
)
