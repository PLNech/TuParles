# Voice command-and-control ergonomics: a meta-language without false positives

*Researched 2026-06-23. Verbatim research brief.*

The hardest problem: telling a **command** ("delete that") from **literal dictation** of the same words. Every mature system has had to solve it. Three families of answers; the canonical tools each lead with a different one.

## How the canonical systems disambiguate command from dictation

### Dragon (30-year incumbent): pause-islands + fixed command grammar + modes
No prefixes. Combines:
1. **Closed command grammar** — only utterances matching a fixed phrase list are *eligible* as commands.
2. **Silence boundaries** — the verbatim rule: **"pause before and after commands, but not within them."** Default gap ~**0.5s** (configurable). Pause inside a phrase → typed as text. Run it into surrounding speech → typed as text.
3. **Modes** override the heuristic: *Normal* (both, pause-heuristic active), *Dictation* (text only — "scratch that" gets typed), *Command* (commands only), plus Spell/Numbers. Switched by voice or hotkey.

Graded form: **"Scratch That <1-10> Times"**; repeating "scratch that" deletes one utterance each time (each repeat its own paused island).

### Talon (modern power-user system, most relevant)
- **Two modes + sleep**: command mode (everything matched against grammar), dictation mode (literal), sleep (wake on **two mouth-pops**).
- **The literal-text escape — the key trick**: in command mode, prefix `"say …"` to type the rest literally. In dictation mode, `escape` forces literal.
- **Non-speech noises as triggers**: **pop** = click, **hiss** = scroll. Used *because* they don't compete with the speech grammar — fire mid-sentence with zero misrecognition risk. **The cleverest idea in the space: move the highest-frequency, most-collision-prone actions off the word channel entirely.**
- **Counts/repeats**: `core.repeat_command(n)`; ordinals; "<command> <number> times"; inline numeric modifiers.
- **Chaining**: multiple commands in one continuous utterance — the headline win over Dragon's one-command-per-pause rhythm.

### Voice-coding tools — three philosophies
- **Serenade**: explicit `dictate`/`command` modes + inline escapes (`phrase`, `escape <symbol>`). Trailing counts.
- **VoiceCode**: *single permanent stream*, no user modes. Parser splits intent from content via **`textCapture`** (grabs prose up to next command keyword) + a **`continuous` flag** (non-continuous commands fire only at utterance *start* — guard against mid-sentence triggering). One-syllable phonetic alphabet.
- **Cursorless**: *sidesteps* collision — verbs are deliberately **non-prose** (`chuck`, `drink`, `funk`), targets are colored "hats" **you can already see**, so a command can't land somewhere unintended.

### Consumer accessibility
- **Apple Voice Control**: modal; "pause ~0.5s between commands"; numbered/grid overlays.
- **Windows Voice Access**: clearest inline escape — prefix **`"Type"` / `"Dictate"`** forces literal entry.
- **Google Voice Access**: overlay-first; system-initiated "Which one?" disambiguation; no documented literal-escape (a gap).

## Unifying design patterns

| Lever | What it does | Cost |
|---|---|---|
| Closed command grammar | small finite set → high in-grammar accuracy | OOG speech misrouted |
| Pause-islands (~0.5s) | silence before+after = command | rhythm tax; fragile under fast speech |
| Explicit modes | strongest guarantee | the textbook **mode-error** trap if invisible |
| Quasimode / push-to-talk | hold key = command mode *only while held* | discoverability |
| Literal escape ("say"/"Type") | forces next words to text | must remember it |
| Non-speech noises (pop/hiss) | high-frequency actions off word channel | limited vocabulary |
| Visible-target addressing | command can only hit what's shown | overkill for plain text |

**Academic spine:** A **mode error** is acting under rules for a state you're not in (Norman; Tesler's "Don't Mode Me In"; aviation "automation surprise"). A silently-switching dictation↔command boundary is exactly this trap. **Raskin's quasimode** (spring-loaded mode) is the cleanest defense: a held key makes the mode self-evident and self-terminating. **Push-to-talk is a quasimode** — structurally eliminates false triggers. C&C grammar vs free dictation (W3C SRGS): smaller + more phonetically distinct grammar → lower false-accept. **Tune toward false-reject for destructive verbs**; make undo cheap and chainable (one study: 66% of time spent fixing misroutes).

## Recommendation for TuParles

### Primary — make commands a quasimode (push-to-talk command key)
We already hold `RCtrl+RAlt` to dictate. Add a **second modifier held = "what I say next is a command."** While held, speech matched only against the tiny command grammar; on release, back to dictation. Highest-leverage decision: structurally removes the ambiguity — no pauses to tune, no false positives from prose, no mode you can forget (the key in your hand *is* the indicator). Raskin's quasimode; why pros run Talon with noises/keys, not pure speech. Fallback: mouth-pop / key-tap as a "command bracket" (open command mode for one utterance, auto-close).

### Pure-voice fallback (no extra key) — three cheap defenses, in order
1. **Closed, phonetically-distinct grammar.** `effacer` is risky (people say it). Use a **repetition signature**: single `effacer` could be prose, but **`effacer effacer`** (doubled, no pause) is vanishingly unlikely as literal dictation — treat the *repeat itself as activation*. Repetition is low-false-positive precisely because humans rarely dictate the same word twice in a row.
2. **Pause-islands** (Dragon's 0.5s): require brief silence before/after a command utterance.
3. **Literal escape** (Windows "Type" / Talon "say"): a reserved prefix — `dis "effacer"` types the word. Without it, the user can never write "delete that."

### Graded / degree commands
- **Repetition = magnitude**: `effacer effacer effacer` deletes 3 units.
- **Explicit count**: `effacer trois`.
- **Relative nudge**: `un peu plus` / `un peu moins` adjusts the *last* deletion's boundary by one unit (stateful "last-edit + delta"). Unit = word by default.

### Safety rails
- **Chainable `annuler` (undo)** — repeat to walk back N steps. The escape valve; lets us bias toward acting since mistakes are one word to reverse.
- **No confirmation dialogs** for deletes (kill flow) — rely on cheap undo.
- **Two redundant mode indicators** (tray color + on-screen toast) so the user is never surprised whether words become text or actions.

### One-line synthesis
> **Push-to-talk command key (quasimode) if you can; otherwise doubled-word activation + pause-island + literal-escape prefix — over a tiny closed grammar, with cheap chainable undo as the safety net.** Reserve any future high-frequency action (cursor nudge, click) for a mouth-pop, not a word.

Same architecture under Dragon, Talon, and the accessibility stacks — they differ only in which lever they lead with. For a local dictation tool, lead with the held key: least code, fewest false positives.

> Caveats: Dragon's 0.5s is documented for v12, user-adjustable. Talon's chaining segmentation isn't formally published. Apple/Google exhaustive command tables live in-product.
