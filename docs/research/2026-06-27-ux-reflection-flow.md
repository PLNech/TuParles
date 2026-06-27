# UX reflection: the dictation flow, end to end

*2026-06-27. A four-facet subagent reflection, seeded by one power-user's live
session (Fr-En code-switcher, RTX 4080 laptop, dictating into Claude Code while
roaming a room with ambient music). Seeds the blog (#42).*

The trigger: a genuine UX insight surfaced by *how the tool was actually used* —
the user wanted to keep dictating while the previous take still decoded ("ctrl-alt
speak, ctrl-alt send, ctrl-alt speak again… never prevent the user from
expressing themselves; capture the flow of thought as it is"). We asked: where
else does real usage reveal leverage? Four reflections, one per flow facet:
**Capture · Feedback · Correction · Delivery.**

## The convergent insight (3 of 4 facets, independently)

**Decisions are being deferred to delivery-time that belong at capture-time.**
Today the daemon answers "where does this text go? what does a newline mean? is
this prose or code?" at the moment of *paste* — when the user has already moved
on, switched windows, lost the context. The fix that keeps recurring is a
first-class **`DeliveryTarget`** captured at take-start and carried with the take:
`(window identity, caret/submit semantics, newline meaning, quote style)`. It is
the single object that unifies four separate "bugs":

- **origin-window delivery** (paste back where you dictated, not where focus is now),
- **target-aware newlines** (Shift+Enter in submit-on-Enter TUIs vs LF in editors),
- **async multi-take** (each queued take needs *its own* destination),
- **code-vs-prose formatting** (one classifier, many consumers).

> Three agents reached for the same image: the Akan talking drum is wasted if it
> speaks into an empty compound — *capture the compound at the moment of speaking,
> not when the echo arrives.* The seam is at capture, not delivery.

## The differentiator insight: render doubt

The product doctrine — *a wrong autocorrect is worse than a visible mishear* — is
**half-implemented**. We refuse to silently fix (right), but we also refuse to
visibly *flag*, leaving the user to discover a confident mishear ("ta courte vie")
downstream. Confidence isn't a number to gate on (rightly banned for
command-vs-text); it's a **texture to render**. faster-whisper already exposes
word-level probability. Brightness is the free channel — hue is spoken for
(green=GPU), motion by state — and doctrine already blesses brightness for "more"
(`[[feedback-signal-more-by-brightness-not-hue]]`). Dim the uncertain word; the
tool stops being a slot machine (jackpot or blank) and becomes a collaborator
that says "I'm with you, but squint at word three."

## The flow insight: dictate in thoughts, not takes

People don't dictate in button-bounded transactions; they dictate in clauses
with prosodic seams (a breath, a falling pitch, a "voilà"). The manual queue is
the mechanical fix; the deeper, doctrine-pure move is an opt-in **continuous mode**
where sustained *silence* (a measurable interlock, never a confidence score)
commits the current clause and re-arms capture — the user pours in at their own
rhythm, the machine keeps up behind them.

## The repair insight: people re-speak, they don't edit

The repair UX assumes surgical edits (delete N, nudge last). The actual reflex is
to **restate the whole phrase, hyperarticulated** — which gives Whisper a fresh
cold-start (worst onset accuracy) AND degrades it (trained on natural prosody). So
the second attempt is often *the same error*. The highest-leverage repair feature
isn't a better edit command; it's making the **second attempt smarter than the
first** (onset context-carryover), plus learning from repeated corrections without
ever crossing into blind autocorrect.

## Prioritized backlog (impact × effort)

### Ship now — pure, low-effort, daily pain
- **Double-punctuation collapse** in `_tidy` (`test, ,`→`test,`) — exact-duplicate
  marks only, never reinterpret. (task #6)
- **Ellipsis** "trois petits points" + `…`, determiner-shielded. (task #7)
- **Target-aware newlines via Shift+Enter** — highest impact-per-effort; unblocks
  the daily Claude Code pain. Send a real soft-newline keystroke between text
  pieces in submit-on-Enter targets (keyname injection, layout-blind, stays clear
  of the xdotool keymap-remap freeze). `newline_mode: auto|lf|shift-enter|crlf`. (task #5)

### The keystone — unlocks the multi-input vision
- **`DeliveryTarget`** captured at take-start (window id on X11 via
  `xdotool getactivewindow`; on Wayland extend the `org.tuparles.FocusWindow`
  extension with `ActivateById`, since clients can't self-refocus). Carries
  window identity + newline + quote semantics. Foundation for:
- **FIFO take queue** — a press while decoding enqueues (audio + DeliveryTarget +
  partial snapshot) and re-arms capture; one worker drains in order; structural
  depth cap (≈5) so a wedged engine can't grow RAM unbounded. (the multi-input ask)
- **Per-take mini-bubbles** (user's choice) — each queued take its own status chip.

### The differentiator
- **Render doubt**: per-word low-probability dimming in partials + final, behind
  `partial_confidence_hint` (default on), measured against the code-switch eval so
  we don't dim correct oral French.
- **Never recant visually**: on a lost final with a painted partial, dissolve from
  the (dimmed) partial + amber "copié — Ctrl+V", not a red flip. The visual half
  of the recovery belt already in `daemon.py`.
- **Backend-shift toast**: one-time "Passé sur CPU — un peu plus lent" when the
  GPU drops, so the beloved green going blue reads as honest, not a bug.

### Repair intelligence
- **Spell-mode quasimode** for acronyms ("en lettres … / spell …" → bilingual
  letter-name table, joined uppercase) — structural, intent-declared, GPU/CPU-identical.
- **Onset context-carryover**: an immediate re-dictation feeds the last delivered
  text as `initial_prompt` tail — fixes cold-start "On vient"→"Rien" at the root,
  bias-only.
- **Correction-pair journal**: log delete→re-dictate pairs locally, *suggest*
  shielded lexicon rules in Réglages, human + eval gate what auto-applies. Learns
  what to propose; never blind `s/cloud/Claude/`.

### Smaller surfaces
- Dev-capture as a Réglages setting (env-var as override-only). (task #8)
- First-audio confirmation pulse ("is it listening?"), device-switch cue, decode
  elapsed counter on long takes, clipboard preserve/restore.

## Recommended arc

1. **Quick wins** (#6, #7, #5) — clear the daily friction, all testable headless.
2. **The keystone** — `DeliveryTarget` → queue → mini-bubbles (the greenlit
   multi-input epic; origin-window paste falls out of it).
3. **The differentiator** — render doubt; it's the most on-brand feature we could
   ship and nobody else's local dictation does it.
