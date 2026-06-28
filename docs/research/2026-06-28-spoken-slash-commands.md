# Spoken slash-commands: driving a REPL by voice — 2026-06-28

## The itch

TuParles dictates *into* things, and increasingly that thing is Claude Code or a
shell. Those interfaces are driven by slash commands — `/compact`, `/help`,
`/code-review`. Dictating one was the worst experience in the product:

- "slash" came back as the literal word **slash**, never the glyph `/`.
- a command name the decoder split stayed split — "pre compact", "code review" —
  so even after you fixed the slash by hand the name was wrong.

The irony wasn't lost on anyone: the moment voice should be fastest (firing a
one-word command at a REPL) was the moment it was slowest.

## Why this is a syntax feature, not a command and not a seed

Three layers could plausibly own this; only one is right.

- **Not `commands.py`** (the edit-command layer, #41). Those are whole-take
  instructions that produce *no text* ("efface efface" deletes; nothing is
  typed). A slash command is the opposite: it IS the text we want delivered.
  Wrong layer.
- **Not the seed prompt** (#68). Tempting — bias Whisper toward "precompact" and
  "code-review" so it stops splitting them. But the Sprint 13 ablation
  (`2026-06-25-transliteration-forensics.md`) measured that over-seeding makes
  the decoder spell things out letter-by-letter and *hallucinate*
  (`J.V.U.K.W.N…`). A push on the acoustics is invisible and hard to undo. We
  want the opposite: a fix you can *see*.
- **Yes, a spoken-syntax family** (#53). Deterministic, post-decode, part-of-a-
  take rewrite, settings-gated, with a place to hang its own interlock. Exactly
  the `quotes`/`caps` shape. So `slashes` rewrites what we already decoded —
  visible, reversible, off-by-a-toggle.

"Rewrite, don't seed" was the first one-liner — and the forensics below overturned
half of it: the post-decode rewrite is the *delivery* mechanism, but the worst
mishear ("c'est l'âge prix compact") has no "slash" in the text to rewrite, so it
*also* needed a small decode-time seed. The surviving principle is the asymmetry:
**a wrong autocorrect is worse than a visible mishear**, so the seed is tiny,
measured, and command-words-only (see "Seeding the command names — now earned").

## The model evolved within the day: "slash" is a path separator

The first cut was cautious — fire only at a **line head**, with a two-tier guard
(known commands free, unknown words only as a bare `slash <oneword>`), because
"slash" is an ordinary word ("slash and burn", "TCP slash IP") and the house
doctrine is *when in doubt, it's text*.

Then the owner tested it and overruled the caution, with data behind the call:
real dictation never opened prose with "slash" — every occurrence was a command,
a path, or a URL. And the line-head anchor was actively wrong for the real use
cases, which are **inline**: "endpoint slash habits" (a REST path), "la slash
memory" (a command mentioned mid-sentence), "code slash slash comment". So the
model became simpler and total:

> **Every spoken "slash" becomes "/", anywhere — a path separator that glues to
> its neighbours.**

- `"slash help"` → `/help`, `"endpoint slash habits"` → `endpoint/habits`,
  `"code slash slash comment"` → `code//comment`, `"et slash ou"` → `et/ou`.
- **Gluing** is between *word characters* — that's where a path component lives.
  The one thing we refuse to fuse is a **sentence break**: a "/" landing after
  `. ? !` keeps its space (`"Bonjour. /help"`, never `"Bonjour./help"`).
- **Ontology canonicalisation** is the one spelling-aware step: `slash` + up to
  three following words are keyed through a separator- and accent-insensitive key
  (`pre compact` / `precompact` / `pré-compact` all → `precompact` → `pre-compact`),
  so the decoder's splits and accents rejoin into the real command name.
- **Accents are trimmed off anything after a "/"** — commands and path segments
  are ASCII; the decoder writes `pré-compact`, the command is `pre-compact`
  ([[history-db]] take tests: "slash pré tiret compact").
- **The hyphen is sayable**: "tiret" / "trait d'union" / "hyphen" → `-` (in the
  punctuation stage), so you can spell a command or identifier out loud.

This *does* relax the when-in-doubt-text asymmetry — a prose "qualité slash prix"
becomes "qualité/prix". Accepted, because for this user "slash" is virtually
always the glyph, and the whole family is one setting (`settings["syntax"]
["slashes"]`) away from off.

## The ontology

A starting set: Claude Code built-ins (`help`, `compact`, `model`, `review`, …)
plus the skills this repo actually leans on (`pre-compact`, `code-review`,
`security-review`, `session-planning`, …) — the names a user of THIS box says out
loud. It's not meant to be exhaustive; `settings["slash_commands"]` extends it
per project with no source edit ("it's a setting"). The canonical (hyphenated)
form is what we emit, so the ontology doubles as a spelling authority, not just a
recogniser.

## Forensics: the take replay (2026-06-28, real voice)

The user dictated commands and URLs with `TUPARLES_DEV` on, so we have the raw
WAVs keyed to history rows. "Forensics before theory" — we re-decoded them
(`scripts/replay_takes.py` machinery, `engine._vocab_prompt` swapped per regime)
instead of guessing. The transcripts already told the story; the replay proved
the fix:

| Take | Said | OFF (no seed) | + command seed |
|------|------|---------------|----------------|
| 16 | "slash precompact" | `C'est l'âge prix compact.` | **`/pre-compact`** ✅ |
| 12 | "slash precompact" | `/pre-compact`† | `/pre-compact` |
| 19 | "slash help" | `/help`† | `/help` |
| 22 | a URL | (dropped) | URL back, `://` still wrong |
| 23 | a URL ×7 | `Httbs.exemple.com` | URL ×n, **+ hallucinated** `facebook.fr`, `google.com` |

†already correct because the post-decode rewrite is now in `postprocess`.

Two findings, and they split the problem cleanly:

1. **Seeding rescues commands.** Take 16 — the decoder hearing "slash precompact"
   as the French phonetic soup "c'est l'âge prix compact" — is the worst case,
   and a command-vocabulary seed flips it to `/pre-compact`. There's nothing for
   a post-decode rewrite to grab there (no "slash" in the text), so this *had*
   to be fixed at decode time. Confirmed again through the real production prompt
   (command seed + manual glossary), not just a hand-crafted one.

2. **But a URL-heavy seed hallucinates** — exactly the failure the 2026-06-25
   ablation warned about. The first seed included example URLs; take 23 then
   *invented* `facebook.fr` and `google.com` that were never spoken. Dropping the
   URL examples (command-words-only seed) kept the take-16 rescue and killed the
   hallucination. So the product seed (`seed_prompt.COMMAND_SEED`) is deliberately
   command-words-only.

## Seeding the command names — now earned

The first draft of this note said seeding had to earn its place against the
metric first (#69). The replay above is that measurement: a small,
command-words-only seed rescues the worst command mishear with no hallucination
tax. So `seed_prompt.COMMAND_SEED` ships, gated by the existing `dictseed_bias`
switch, riding the protected tail with the manual glossary (never trimmed).

## URLs are the harder sibling — a dictation mode, not a seed

"https deux-points slash slash nech point exemple point com" is the same shape
(spoken symbols → a technical string) but a harder problem, and the forensics say
so: the decoder *acoustically* fuses "deux-points" → "2" ("https2…") and drops
"slash slash", so there's often no clean symbol-word left for a post-decode map
to catch — and a URL-shaped seed hallucinates. Neither lever this turn used
(seed, rewrite) solves it.

The right answer is a dedicated **dictation / spell mode** (a quasimode, kin to
#62): the user signals "I'm dictating a literal technical string", and inside
that mode we map symbol words aggressively ("deux-points" → `:`, "slash" → `/`,
"point" → `.`), glue without spacing, and maybe disable the partial-decode echo.
That's a real feature, scoped separately — not hacked in behind this one. Filed
as the follow-up; this note is its motivation.


## Measure

The load-bearing test is `tests/test_slashes.py`: command canonicalisation (incl.
the user's literal "slash pre/precompact/pré-compact" → `/pre-compact`), the
separator-everywhere cases (inline paths, `//`, prose glue), accent trimming
(`/cafe`), the spoken hyphen ("slash code - review" → `/code-review`), and the
one boundary we protect — a "/" after a sentence break keeps its space.
`tests/test_seed_prompt.py` pins the command seed riding the protected tail and
surviving the budget trim; `tests/test_punctuation.py` covers "tiret" → `-`.
End-to-end through `pipeline.postprocess()` confirms the punctuation and casing
stages don't break the match.
