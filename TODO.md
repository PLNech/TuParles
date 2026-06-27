# TODO — TuParles backlog

Snapshot for cold-start recovery. The task system is the live source of truth;
this file mirrors it so a future session can resume without the transcript.
Last synced: **2026-06-27** (end of Sprint 20 "Le visage honnête").

State at sync: `main` clean and pushed. Shipped this sprint — #27 (UI honesty),
#28 (capture cues + type-safe clipboard restore), #8 (dev toggle + tray dot),
#29 (cross-env capability layer + docs/templates/`diag`), #21 (Span model).

---

## The doubt-rendering epic (the marquee chain)

The half-built doctrine — *a wrong autocorrect is worse than a visible mishear* —
becomes visual. We refuse to silently fix; this chain lets us visibly **flag**.
Keystone #21 (Span model) is **done**. Remaining legs, in order:

```
#21 ✓ ──► #22 ──► #24 ──► #16
              └──► #25
#21 ✓ ──► #26
```

### #22 — Span-aware pipeline: postprocess annotates origin  *(next up, M, delicate)*
- **blocked by** #21 (done) · **blocks** #16
- Add `postprocess_spans(transcription) -> list[Span]` running the **same**
  transforms as `postprocess` but annotating each span:
  - spoken-punctuation → `inserted` punct spans
  - lexicon hit → `rewritten` (carry `original`)
  - quotes/caps syntax → `inserted`/`rewritten`
  - casing → `cased` (surface change, keep confidence)
  - repeat-collapse → `collapsed`/dropped
- **Keep `postprocess(str) -> str` as the canonical eval-pinned path.** The span
  path must `flatten()` **identically** — property test vs the code-switch corpus.
- **Confidence mapping:** decoded word spans inherit engine word-probability;
  `inserted`/`rewritten`/`cased` spans are DELIBERATE = **certain** (we never cast
  doubt on our own edits — doctrine-clean).
- Daemon + eval still call `postprocess`; UI consumes spans.
- **RECOMMENDED low-risk design:** build the span path *parallel* to the string
  path — never rewrite `postprocess()` itself, never touch delivery's string spine.
  Pin `flatten(postprocess_spans(t)) == postprocess(t)` byte-for-byte first, then
  grow the annotations. Deserves its own focused session (L-effort guidance: don't
  tail it onto polish work).

### #24 — UI: per-span rendering (doubt via brightness)  *(M)*
- **blocked by** #21 (done) · **blocks** #16, #25
- Make `ui._paint_text` span-aware: paint each span; word spans with confidence
  below threshold get `_TEXT_DIM`, confident words `_TEXT_LIVE`.
- **Brightness channel ONLY** (hue = GPU green, motion = state — the colour
  contract; see `[[feedback-signal-more-by-brightness-not-hue]]`).
- Inserted punctuation renders normally (or a subtle distinct tone — TBD).
- Behind `partial_confidence_hint` (default on). Measured against the code-switch
  eval so correct oral French isn't dimmed.
- Headless-test the colour decision as a pure span→pen mapping.

### #16 — Render decode doubt via per-word brightness  *(the visible payoff, S–M)*
- **blocked by** #21 (done), #22, #24
- Dim low-probability words (faster-whisper word probability) in partials + final,
  **never rewrite**. Brightness channel only.
- Behind `partial_confidence_hint` (default on), measured against code-switch eval.
- The most on-brand differentiator: the "visible mishear" doctrine made visual.

### #25 — Partial→final / punctuation-parsed transition  *(M)*
- **blocked by** #24
- Partials = raw decoded spans (no punctuation, all decoded-confidence); final
  swaps in the parsed/punctuated stream. Relayout the bubble smoothly when
  punctuation/quote spans appear (no jarring reflow), so raw→clean reads as
  "parsing happened", not "glitch". Span-diffable, not string-replace. Optional
  settle animation / postprocess-pending hint.

### #26 — Rewrite surfacing: Span.original → reveal X→Y  *(S, independent)*
- **blocked by** #21 (done) — can ship without #22/#24
- Spans carry `original` on `rewritten`/`cased`/`collapsed` edits. Surface them:
  setting `show_rewrites` marks edited spans (subtle underline/tone) so the user
  sees we changed X→Y (never-hide-a-mistake, made visible not silent).
- Feeds #19: a rewrite the user then re-edits = signal the rule was wrong.
- Default **off** (quiet), opt-in for power users / debugging.

---

## Parked — needs voice (user muted at sync)

### #30 — Engine-lock priority: stop new partials starving the committed decode  *(M)*
- The remaining duration-dependent lag. With the queue, a finishing take's final
  decode and the NEXT take's partials both contend on `_engine_lock` (one GPU).
  Journal shows `lock_wait` 0.17–0.28s on back-to-back takes.
- Options, **pick by measurement** (back-to-back repro, per-partial `lock_wait`):
  - (a) final (committed text) preempts / takes priority over partials
  - (b) suspend the partials loop while the decode queue is non-empty
  - (c) cancel an in-flight partial when stop fires
- NOT GIL-bound (faster-whisper releases GIL in C++) — it's lock ordering.
- Relates to the user's "review multiprocess/nice/priority" ask.

### #31 — Validate delivery fixes live  *(S, validation)*
- Next-session live confirmation of Sprint 19 fixes; watch
  `grep "hotkey: press ignored|armed|delivered|toggle ignored"` in `/tmp` journal:
  1. **xprop class fix** — terminal targets (kitty, Claude Code) paste via
     Ctrl+Shift+V and land. Confirm no more "un sur deux" into terminals.
  2. **Debounce 0.12s** — rapid start→stop→start-next all register, no spurious
     "press ignored"; if they appear, lower further or make it a setting.
  3. **Origin-window dance** (`deliver_to=origin`) — never validated under REAL
     overlap: dictate into A, switch to B mid-decode, confirm A's text lands in A
     and focus returns to B. If intrusive, document `deliver_to=current`.
  4. **Queue chips** — only show on genuine overlap (`pending>1`), rare with fast
     GPU. Decide if fine, or chip a single in-flight take too.
- Close the loop or file follow-ups per finding.

---

## Standalones (parallel-safe, no hard deps)

### #32 — Capture cues round 2: first-audio pulse + device-switch toast  *(S)*
- Deferred from #28. Both small; want a clear payoff before more bubble motion.
  - (a) **First-audio pulse** — flash the bubble border on the first *real* audio
    block after start (audio arrived, not just "we called start"). Only add if it
    earns its place against the live waveform, which partly serves this already.
  - (c) **Device-switch cue** — when the mic falls back to default mid-session
    (currently only journald). Needs recorder→bridge plumbing.

### #17 — Spell-mode quasimode for acronyms  *(M)*
- Trigger `en lettres …` / `spell …` switches the remainder to letter-assembly via
  a bilingual letter-name table (erre→R, double v→W, NATO alpha→A), joined upper.
- Structural / intent-declared like literal-escape; unknown token passes through as
  text (visible, never silent mangle). Optional `initial_prompt` hint when armed.
- Fixes SRE→"S R I". See `[[feedback-structural-command-disambiguation]]`.

### #19 — Correction-pair journal (safe learning)  *(M)*
- Log delete→re-dictate pairs locally; surface **shielded lexicon-rule
  SUGGESTIONS** in Réglages (e.g. `cloud`→`Claude` only adjacent to
  `code`/`anthropic`). Human + code-switch eval gate what auto-applies.
- Learns what to propose, **never blind autocorrect**. On-device only.
- Fed by #26 (a re-edited rewrite is a wrong-rule signal).

### #20 — Continuous silence-segmented capture (opt-in)  *(L)*
- Opt-in mode: sustained silence (measurable interlock, never a confidence score)
  commits the current clause to the queue and re-arms capture — dictate in your own
  rhythm, machine keeps up behind. The doctrine-pure "capture the flow of thought".
- Depends on the decode queue (shipped Sprint 19, #14).

### #12 — snapshot() lock hygiene (not the freeze fix)  *(S, low priority)*
- `snapshot()` concatenates the whole buffer under the recorder lock, blocking
  `_on_block`. Copy chunk refs under lock, concatenate outside.
- Good hygiene but advisor showed it is **NOT** the episodic freeze cause (take 157
  was longer + instant). Ship **un-labelled** as a perf tidy.

---

## Suggested next-session order

1. **#22** — span-aware pipeline (its own focused session; the spine work that
   unblocks the marquee #16). Parallel `postprocess_spans`, invariant pinned first.
2. **#24 → #16** — the visible doubt-dimming payoff, once #22 lands.
3. **#26** — independent of #22/#24; a cheap, on-brand win any time.
4. When voice returns: **#31** (validate live) and **#30** (engine-lock, measure
   first).
