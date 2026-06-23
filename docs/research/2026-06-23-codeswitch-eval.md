# A measurement substrate for code-switching — design notes

*2026-06-23. Build note for task #51. Companion to the
[voice UI command & control brief](2026-06-23-voice-ui-command-control.md) and
the moat tasks #34 (real-use validation) and #49 (code-switch fine-tune).
Records why we built an adversarial eval suite and how each call went.*

## Why now: the bug that named the gap

Dictating *"fan out les agents"* into TuParles produced **"tu fais un air de
jamais les agents."** The English particle verb *fan out* collapsed into French
*fais un air* — the model heard French phonemes where English words were meant.
That is the entire failure class TuParles exists to fight, and we had no way to
*measure* it. We had a thesis (multilingual decoding follows the switch) and
anecdotes, but no number that moves when the decoder gets better or worse.

You cannot improve a moat you cannot measure. #49 (fine-tune) and #34
(validation) both presuppose a yardstick. This is the yardstick.

## What it is

A reproducible, adversarial, FR-EN code-switch evaluation harness:

1. **A corpus** (`tests/data/codeswitch/corpus.json`) — sentences a
   French-speaking developer would actually dictate, each chosen because an
   English token sits exactly where French phonetics wants to swallow it.
   Categories: English particle-verb borrows (*fan out*, *spin up*, *roll
   out*), cross-lingual homophones (*ship*/*chip*, *cache*/*cash*/*caché*),
   mid-sentence switches (*review ma pull request avant le standup*), English
   numbers as jargon (*five nines*, *two hundred milliseconds*), spoken
   acronyms (*la CI tourne l'API et le LLM sur le GPU*). Seeded with the real
   *fan out* misfire — **the bug is the first test.**

2. **Multi-engine WAV generation** (`scripts/gen_codeswitch_wavs.py`) — renders
   each case through several voices. The deliberately useful trick is
   *cross-lingual voicing*: a **French** voice reading the English tokens
   produces authentic franglais phonemes, the exact acoustic that trips
   Whisper. Two engines: **piper** (local neural, realistic prosody, CPU) and
   **espeak** (formant, robotic but a different failure surface — a useful
   second opinion). Everything is normalised through ffmpeg to 16 kHz mono
   s16le, so the harness loads it into exactly the int16 array the microphone
   path produces.

3. **A scorer** (`src/tuparles/eval.py`) with two signals, by design.

4. **A gated integration test** (`tests/test_codeswitch_eval.py`) that runs the
   **full user-facing pipeline** — decode → `pipeline.postprocess` (punctuation
   + lexicon + repeat-collapse) — so a pass means *what the user would have
   seen* survives, not merely that raw logits were fine.

## The two signals (and why not one)

- **Slot checks are the gate.** Each case declares the tokens that MUST survive
  (`must_contain`: "fan out") and the misfire it collapses into
  (`must_not_contain`: "fais un air"). Pass iff all required phrases present and
  no misfire present. This targets the adversarial point — specific words — not
  whole-sentence fidelity.
- **WER is the trend, never the gate.** Word error rate against the reference
  transcript is reported but never fails a case: a harmless rewording
  ("c'est"/"c est") should move the number without flunking the decode. It
  tells us whether decoding drifts overall, between models or releases.

Exact-match scoring would be the wrong bar for ASR (constant false negatives);
a pure WER threshold punishes harmless variance as hard as real misfires. Slots
+ WER separates "did the trap spring" from "how clean was the rest".

Matching is on *contiguous token sublists* after an NFC + casefold +
de-punctuate normalize, so "fan out" can't spuriously match inside "fan outil",
and "fan-out"/"fan out" compare equal — the spelling of the seam is not what we
test.

## Calls made

- **Test the full pipeline, not raw Whisper.** The daemon's post-processing was
  inlined; we extracted `pipeline.postprocess()` so the daemon and the harness
  run the *identical* path. A test that skipped post-processing would measure a
  fiction the user never sees.
- **Gate, don't fail, when the box can't run it.** The integration test is
  marked `gpu` (deselected by default) and skips — never errors — without a
  CUDA device or without generated WAVs. The pure-python scorer and corpus
  integrity, by contrast, run in CI now: the corpus is itself under test (no
  duplicate ids, every `must_contain` actually present in its own reference,
  every `must_not_contain` actually absent — a case that can never pass, or can
  never fail, is a bug in the case).
- **Synthesis is a reproducible proxy, not ground truth.** TTS franglais is not
  a human code-switcher; it is a cheap, deterministic, regenerable stand-in. The
  harness loads *any* 16 kHz mono WAV + expected slots, so real recordings drop
  in later under the same scorer. WAVs and the 60 MB neural voices are
  gitignored; `corpus.json` is the source of truth and regenerates them.

## Open / next

- **Run it on the GPU box** (post-reboot) — the first real numbers. Expect some
  red; red cases are the backlog for #49 and the lexicon (#31).
- **Grow the corpus from real misfires.** Every embarrassing decode becomes a
  case. The corpus is a living regression net, not a fixed benchmark.
- **Feed confirmed, reproducible misfires into the lexicon** (#31) only where
  the fix is unambiguous — the eval tells us which mishears are systematic
  enough to earn a deterministic rewrite.
- A WER trend line across models would make #49's "turbo ranked worst on
  code-switch" claim concrete rather than cited.
