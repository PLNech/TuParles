# Voice commands, the local way — design notes

*2026-06-23. Companion to the [voice UI command & control brief](2026-06-23-voice-ui-command-control.md)
and the [Genspark Speakly deep-dive](2026-06-23-genspark-speakly-deep-dive.md) §5 decision 3.
Records what we built for task #41 and, more usefully, why each call went the
way it did.*

## The cloud foil, and our answer

Genspark Speakly's headline trick is "Agent Mode": double-tap a key and a
cloud agent does a task for you — "build me a slide deck", "summarise and
email this". It is genuinely useful and it is genuinely their cage: it only
works because a model in a datacenter reads your screen and your words. It is
unpredictable (a model decides what you meant), it is a round-trip (latency,
network, outage), and it is the opposite of private.

We deliberately do **not** chase that. The honest local answer is narrower and
better-behaved: a small, fixed, **deterministic** command vocabulary that acts
on *your* text in *your* editor, with no model and no round-trip. You always
know exactly what each phrase does. That is the whole pitch — not "an agent
that might do what you meant", but "a tool that does what you said".

## The one hard problem: command vs dictation

Every voice-command system lives or dies on a single question: *was that an
instruction, or was it text I wanted typed?* Get it wrong toward false
positives and the tool edits the user's prose against their will — the
unforgivable failure. Get it wrong toward false negatives and a command gets
typed out instead of run — mildly annoying, instantly retried.

So the bias is asymmetric and absolute: **when in doubt, it's text.** We would
rather miss ten commands than fire one we shouldn't.

The lead design in the research is a *quasimode* — hold a second modifier and
the next words are a command, never text. Structurally it makes false
positives impossible: no held key, no command. That's the richer follow-up.
What shipped first is the **pure-voice** layer, because it needs no changes to
the hotkey path and is fully unit-testable without a GPU — and because its
safety comes from structure too, not from a confidence threshold:

- **Delete requires a *doubled* trigger** — "efface efface", "delete delete".
  Nobody doubles a verb in natural speech, so the doubling *is* the interlock.
  A single "efface" is always prose.
- **Undo / nudge / open-terminal** are a tiny whitelist of short *exact-match*
  phrases. "annule" alone is enough (undo is reversible and safe); the
  collision-prone bare words ("plus", "more", "encore") are deliberately *not*
  commands.
- **Length is a guard.** Anything past a handful of words is dictation, full
  stop — commands are terse.
- **Literal escape** — 'dis "efface efface"' — lets you actually dictate the
  word. But it only fires when the remainder would *itself* be a command, so a
  sentence that merely starts with "dis" or "say" stays ordinary prose. You
  escape something only when there's something to escape.

The test suite leads with an adversarial **prose corpus** — sentences that
name "efface", start with "dis"/"say", carry a lone trigger or a buried "un
peu plus" — and every one must classify as *not a command*. That corpus is the
real spec; the grammar is just what's left once misfires are impossible.

## The grammar (v1)

| Say | Result |
|-----|--------|
| efface efface | delete 1 word |
| efface efface efface | delete 2 words (each extra repeat = +1) |
| efface efface trois mots / 5 mots | delete N words (FR/EN number words + digits) |
| efface efface un caractère | delete chars |
| efface efface la ligne | delete to line start |
| efface efface tout | select-all + delete |
| delete delete two words | same, in English (code-switch is the moat) |
| annule / annuler / undo | undo one step (chainable) |
| un peu plus / a bit more | one more unit of the last edit |
| un peu moins / a bit less | undo one step |
| ouvre un terminal / open a terminal | spawn a terminal |
| dis "efface efface" | type the words instead of running them |

Execution reuses the existing paste backends — xdotool on X11, ydotool on
Wayland — with the same best-effort contract: a keystroke that fails is
logged, never raised, because a missed edit just gets redone but a crash takes
the daemon down. `ctrl+BackSpace` deletes a word in essentially every text
widget; `shift+Home`+`BackSpace` clears a line; `ctrl+a`+`BackSpace` clears
all; `ctrl+z` undoes. Universal, dumb, predictable.

## What we deliberately left out

- **The held-modifier quasimode** — the richer, even-safer activation. Pure
  voice shipped first because it's testable today and needs no hotkey surgery.
- **"mets en bullets" and friends** — a *transform* of text, not an *edit* of
  the editor. That's a mode/template, so it belongs with task #47, not here.
- **Sentence-unit deletion** — no keystroke deletes "a sentence" reliably
  across apps, and an unreliable edit is worse than an honest refusal. Word,
  char, line, all only.

## Open: needs a real session

The Wayland keystroke path mirrors the shipped paste path but hasn't run on a
live Wayland session (dev machine is X11), and the whole layer hasn't been
exercised end-to-end through real dictation yet (no GPU this session). Both
fold into the real-use validation pass (#34) — the same doctrine that's paid
off all along: forensics before claims, measure before you trust.
