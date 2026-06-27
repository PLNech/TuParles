# The honest face: small polish, big trust (#27, #28)

*2026-06-27. A convenience sprint off the UX reflection (`2026-06-27-ux-reflection-flow.md`).
Nothing architectural — just the tool learning to *read* honestly. Seeds the blog (#42).*

Four small features, one thread: **own the truth of what just happened.** A tool
you talk to all day earns trust not in its happy path but in how it behaves when
something goes sideways — a lost decode, a dropped GPU, a slow take, a clobbered
clipboard. Each was a place the tool was quietly *less than honest*.

## Never recant (#27)

The doctrine is *a wrong autocorrect is worse than a visible mishear*. The
recovery belt (#10) already copies a salvaged partial to the clipboard when the
final decode is lost — but it then **red-flashed an error**, visually *taking
back* the words the user had just watched stream in. That's a recant: the screen
said "actually, nothing." Worse than the miss.

The fix is a rendering decision, not a logic one. A new amber **`recovered`**
state keeps the dimmed partial *on screen* — the words don't vanish — with a
`Ctrl+V` badge and a longer dwell. Amber, not red: **held, not failed.** It rides
its own signal (`recovered`), so the red `error` channel stays reserved for
genuine failures. The colour grammar already had room: green/blue = which
silicon, brightness = landed, red = error. Amber slots in as "provisional,
saved" without overloading a hue.

And the no-partial case softened too: *"Rien entendu"* → *"Je n'ai pas bien
saisi."* A lost decode is the tool's miss to own, not the user's voice to blame.

## Name the fallback (#27)

When the GPU dies mid-session (suspend/resume kills the CUDA context, see
`ResilientEngine`), the bars go green→blue. Honest in colour — but a silent
colour shift *reads as a bug*. One sticky, once-per-session toast — *"Passé sur
CPU — un peu plus lent"* — turns a mysterious change into a stated fact. Said
once (the fallback is sticky), gated by a setting, emitted *after* the take's
final flash so the notice wins the bubble (the text already landed in the
window).

## Working, not frozen (#28)

A long CPU decode looks identical to a hang. A dim `(Ns)` counter past 3 s is the
whole fix: *working (12s)* reads completely differently from a frozen pill. The
clock is injectable, so the threshold and the counter are headless-tested with no
`sleep` anywhere.

## The clipboard is typed — the sharpest lesson

The obvious version of "preserve the clipboard around a paste" is: read it,
paste, write it back. **That version destroys data.** The clipboard is not a
string — it's a set of typed offers (`UTF8_STRING`, `text/plain`, `image/png`,
`text/uri-list`, …). A *text* tool (`xsel -o`, `wl-paste`) reading an image
returns nothing, and writing that empty string back **deletes the user's image**.
Implicit data destruction wearing a "convenience" hat.

So the feature is type-aware by construction. `is_text_clipboard()` enumerates
the offered targets (`xclip -t TARGETS` / `wl-paste --list-types`) and bails on
anything non-text — *before* any restore. A subtle trap: `text/uri-list` (a copied
*file list*) wears a `text/` prefix but is not plain text, so the reject check
runs **first**, ahead of the text match. When unsure (no tool, no targets), it
returns False: leave the clipboard alone. The default is **off** — the safe
choice never risks the core paste — and the tradeoff (the dictated text is no
longer left for a manual re-paste) is stated in the tooltip. It's a setting.

> The lesson that travels: an *output path you didn't create is not yours to
> overwrite* — and that includes the clipboard. Before writing, find out what's
> already there. A "restore" that doesn't check the type isn't a restore, it's a
> shredder with good intentions.

## What we deferred (on purpose)

#28 also floated a **first-audio confirmation pulse** and a **device-switch
toast**. The pulse we dropped: the live waveform already *is* the "it's
listening" cue — adding a second one would gild it. The device-switch toast wants
recorder→bubble plumbing for a rare event; it stays in the backlog rather than
pad the sprint. Saying what you *didn't* build is part of an honest face too.
