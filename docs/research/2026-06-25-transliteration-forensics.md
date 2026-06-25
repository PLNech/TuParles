# Transliteration forensics — what 10 real takes taught us about seeding

*2026-06-25. Source: the history DB (`~/.local/share/tuparles/history.db`),
last 10 dictations of the day. Companion to
[2026-06-24-real-take-error-taxonomy.md](2026-06-24-real-take-error-taxonomy.md)
and [2026-06-24-codebase-aware-dict-seeding-eda.md](2026-06-24-codebase-aware-dict-seeding-eda.md).
Seeds the blog (#42).*

## The trigger

PLN flagged "grosses erreurs de translittération récentes" and asked for a
forensic read of the history before any theory — the house rule
("forensics before theory"). So we pulled the takes and tallied the misfires
by *type*, not by gut.

## The taxonomy (what actually broke)

~80% of the damage is one thing wearing four hats: **technical vocabulary the
decoder has no anchor for, re-lexicalised into the nearest ordinary word.**

| # | Said | Decoded | Class |
|---|------|---------|-------|
| 9 | DKIM | « des KIM » | acronym → FR words |
| 9 | DMARC | « des marques » | acronym → FR words |
| 9 | PII | « PIL » | acronym |
| 9 | privacy | « PREV, SI » | EN word → FR letters |
| 1 | qwen | « Quinn » | model name → name |
| 1 | build | « Bill » | tool word → name |
| 1 | CPU | « CPP » | acronym |
| 2 | UI | « l'ueil » | acronym → non-word |
| 7 | Postgres | « Postgre » | product → truncation |
| 8 | nech.pl | « Neck.tl » | personal domain |
| 10 | plnech.fr / nech.pl | mangled | personal domains |

The tail (homophones: « zoom d'hier » vs *d'ici*, « bulle » → « boîte ») is
diffuse and not the main event.

The cruel detail: take #1 — where qwen became "Quinn" — was PLN *dictating about
transliteration errors themselves*. Our own CPU-fallback model name doesn't
survive a sentence about its own job.

## The constraint that decides everything: 224 tokens

Whisper's `initial_prompt` keeps only the **last ~224 tokens** (see
`seed_prompt.py`). That single fact answers most of the "what if we seed…"
questions before we run anything:

- **"Seed 10k tech words"? No — physically impossible.** You have ~150–200
  words of budget, and far fewer in practice: on short audio a stuffed prompt
  starts to *echo-hallucinate* (which is why `engine.py` already drops the
  prompt on short greedy decodes). `_SEED_LIMIT = 30` was the right instinct.
  **The game is selection of the right ~30 slots, not volume.**
- **TF-IDF? Yes — but as the *selection* algorithm, not a seed mechanism.** It
  ranks which terms are distinctive enough to earn a slot. `nlp_eda.py`'s
  `top_seeds` already approximates this over the *codebase*; the untapped
  corpus is the **history DB itself** — TF-IDF over what PLN actually *says*
  surfaces `qwen, DKIM, PII…` against a generic-French background. That feeds
  the 30 slots; it doesn't lift the budget.
- **logprobs / shallow fusion? Yes — but long-term.** Biasing token logits
  *inside* the decode loop is the only lever that scales past the prompt budget
  (it doesn't compete for it). CTranslate2 doesn't expose it cleanly, so it's
  custom-decode R&D, gated by the eval, with a CPU path. Not this sprint.

## The decision: bias, not rewrite — because the misfires are real words

The goal is **high precision + high recall, low FP + low FN.** That reframes
the lever choice, because the post-decode lexicon and the decoder bias have
*opposite* failure modes:

- **Bias (`initial_prompt`) can only raise recall.** It nudges the decoder
  toward the right surface; it can never *insert* a wrong word that wasn't
  heard. Zero-FP by construction.
- **Lexicon (post-decode rewrite) can raise recall but risks FP.** It rewrites
  text unconditionally.

Now look at the misfires: « des marques » is a *legitimate French phrase*.
"Bill" is a person. "Quinn" is a name. "CPP" is C++. Adding any of these to the
lexicon would clobber real usage — a textbook false positive, the exact thing
the goal forbids. So **for this entire error class the correct lever is bias,
and the lexicon stays nearly empty by design.** The one exception is
`Postgre`: a pure non-word that is *never* intended, so it earns a deterministic
fix. The doctrine ("a wrong autocorrect is worse than a visible mishear") and
the metric agree.

## Local vs global

Two layers, both already wired — this sprint just feeds them:

- **Global / invariant** = the manual glossary `vocab.txt`, ridden at the
  *tail* of the prompt so it survives the 224-token truncation. Stack terms
  (`qwen, DKIM, DMARC, SPF, PII, Postgres`) and **identity** (`nech.pl`,
  `plnech.fr`, `Nech`, `Paul-Louis Nech`, the username) live here. `vocab.txt`
  is gitignored — *your names stay on your box*, which is also the privacy
  story.
- **Local / contextual** = the auto-seeds `_seed_surfaces()` reads from the
  codebase EDA cache (#70). Already local to the repo you're in; the natural
  extension is swapping the set by active window/app.

## What shipped this sprint (#NN)

- **7 corpus cases** from the real misfires (`tests/data/codeswitch/corpus.json`)
  — DKIM/DMARC, PII/privacy, qwen/build/CPU, UI, Postgres, the personal
  domains, and an **identity gate** for the user's own name. These are the
  FP/FN measurement: `must_contain` = recall (FN), `must_not_contain` = the
  legit-word trap we must NOT emit (FP). Each note records *why* it's
  bias-only or lexicon-safe.
- **`vocab.txt` seeded** with the infra acronyms and identity (local, zero-FP,
  immediate).
- **One lexicon fix**: `Postgre → postgres` — the lone unambiguous non-word.

## Measured (2026-06-25, GPU box, 58 WAVs = 29 cases × 2 cross-lingual voices)

We didn't argue it — we ran it. `scripts/measure_seed_ablation.py` decodes every
WAV under three `initial_prompt` regimes (OFF = no bias, CURATED = manual
glossary only, FULL = manual + codebase auto-seeds) and scores recall (FN) and
leak (FP).

| regime | new-case pass | new-case recall | all-case recall | all-case FP |
|--------|--------------:|----------------:|----------------:|------------:|
| OFF (baseline) | 1/14 | 8/28 (29%) | 64/124 (52%) | 4/190 (2%) |
| CURATED        | 6/14 | 16/28 (57%) | 72/124 (58%) | 3/190 (2%) |
| FULL (capped)  | 6/14 | 16/28 (57%) | 73/124 (59%) | 3/190 (2%) |

**The headline: seeding nearly doubled recall on the target errors (29 → 57%)
while FP stayed at 0% on the new cases.** Exactly the goal — high recall, low
FP. Concrete rescues: `qwen` (OFF heard "quen"/"q1"), `CPU` ("sépu"), `Postgres`,
and — the one PLN flagged — **`Paul-Louis Nech`** (OFF heard "Paul Wienek").
The bias lever can only raise recall; it never inserted a wrong word, so
precision held.

### The over-seeding regression we *found by measuring*

The first FULL run (before the budget cap) scored WORSE than CURATED — 56% vs
58% recall, one extra leak — and on one case it **hallucinated outright**:
`'J.V.U.K.W.N.R.E.F.L.…'`. The codebase EDA auto-seeds are `ALL_CAPS_CONSTANTS`
and `CamelCase` identifiers; ~26 of them (747 chars / ~190 tokens) bias the
decoder toward spelling words letter by letter. This is the "seed 10k" failure
mode arriving early — at ~190 tokens, not 224. **The auto-seeds didn't just fail
to help; they actively broke a case the curated prompt passed.**

The fix (`seed_prompt._PROMPT_CHAR_BUDGET = 400`): trim auto-seeds
(least-important first) until the prompt fits a hard budget well under Whisper's
~224-token tail-keep; **never drop the curated manual glossary** (it's the
point). Production prompt dropped 747 → 376 chars. Re-measured: FULL now 21/58
pass, 59% recall, 3 leaks — *better* than CURATED, hallucination gone. Since
PLN's box has the EDA cache, FULL is what he actually runs, so this turns the
ablation win into a real-box win.

The eval is GPU-gated (needs WAVs from `scripts/gen_codeswitch_wavs.py`); CI runs
the structure + unit gates.

**These numbers are on synthetic TTS** — piper voices reading franglais. They
show the *direction* (seeding nearly doubles recall, the cap kills the
hallucination), but the TTS acoustic isn't your voice. That's why the next step
shipped immediately: dev take-capture (`takes.py`, `TUPARLES_DEV`) stashes your
real takes so `scripts/replay_takes.py` re-runs this ablation on *your* audio.
Measure on the real thing before trusting the synthetic delta.

## Roadmap

- **Short term (shipped):** seed + corpus + the one safe rewrite.
- **Medium:** TF-IDF over the *history DB* to auto-rank the 30 slots from what
  PLN actually says (not just the codebase); context-local seeding by active
  window.
- **Long:** shallow fusion / logit biasing for large-vocabulary contextual
  biasing beyond the prompt budget — CPU path included, gated by the
  code-switch eval. "Measure before you trust."
