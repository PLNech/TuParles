# A real take, decoded raw: an error taxonomy and the prior it argues for

**2026-06-24.** A user dictated a ~250-word French monologue (a game-design
brief) into a *greenfield* `claude.ai/new` field — **zero context to attach
to**, so no dict-seed, no glossary, no live signal. That makes it the purest
specimen we have: the bare decoder's raw behaviour. Forensics before theory.

## The transcript's errors, by class

| Heard (raw) | Intended | Class | Fixable by us? |
|---|---|---|---|
| `des épiailles` | `des APIs` | code-switch **acronym-borrow** | yes — pre-decode bias |
| `highscore` ×2 | `highscore` ✅ | en-noun survived | pin it (regression) |
| `replayable` | `replayable` ✅ | en-adj survived | pin it |
| `self-contained` | `self-contained` ✅ | en-compound survived | pin it |
| `Charles de ville` | `Charlottesville` | proper-noun **split** | only with context |
| `Tombout` | `Tombouctou` | proper-noun **truncation** | only with context |
| `rendu Delhi` | `New Delhi` *(tentative)* | proper-noun | only with context |
| `Dubai` / `Dubaï` | one city, two spellings | **intra-take inconsistency** | yes — canonicalize |
| `Phénix` | `Phoenix` | city/bird homograph | borderline |

The four code-switch cases (1 misfire + 3 survivals) are now in the
code-switch corpus (`tests/data/codeswitch/corpus.json`). The proper-noun
casualties are **not** — they're a different class the text pipeline can't
touch (see below), and they'd dilute the FR-EN homophone focus.

### The `épiailles` tell

`/e.pi.aj/` matches the **English** pronunciation "ay-pee-**eyez**," not French
"a-pé-i." So it's a code-switched *plural* acronym, and the trailing `-z` of the
spoken plural is exactly what dissolves into `-ailles`. Confirmed by the user;
"in our ICP's speech, `APIs` is overwhelmingly more frequent than `épiailles`"
— which is the entire argument for a frequency prior.

## Three walls that decide the fix

1. **Acoustics are gone.** By the time text reaches our pipeline,
   "Charlottesville" is already "Charles de ville." No post-hoc rewrite recovers
   a *destroyed* rare noun without inventing meaning — and *a wrong autocorrect
   is worse than a visible mishear* (the lexicon doctrine). So the leverage is
   **pre-decode bias**, not correction.
2. **The 224-token wall.** Whisper keeps only the last ~224 `initial_prompt`
   tokens (learned in #68). You cannot dump a gazetteer or a spaCy entity list
   into the prompt. Bias must be **few + relevant** — which forces *ranking*.
3. **Relevance needs context — greenfield has none.** First-time recovery of a
   destroyed rare proper noun with zero context is near-impossible. Don't chase
   it. Bank the achievable wins instead.

## The achievable wins, ranked

1. **Intra-take consistency** (cheap, low-risk): `Dubai`/`Dubaï`, repeated
   `Phoenix` — locate entity spans, canonicalize repeats to the
   highest-confidence spelling within the take. No external data.
2. **Live-context entity seeding** (highest real-world ROI; #70/#71): real
   dictation usually *has* context — the open editor, clipboard/selection, the
   file you're in. Seed *those* entities into the prompt tail. The claude.ai
   case is the pathological one (we can't see the page); #71 (clipboard/
   selection) is the escape hatch.
3. **Confidence-gated two-pass re-bias** (the experimental moat): we already do
   greedy-partial → beam-final. faster-whisper hands us **word-level logprobs
   for free** — low-confidence spans are an entity/corruption locator, *no
   spaCy needed*. Fuzzy-match those spans against the contextual term-set; on a
   single high-confidence hit, bias the final beam pass (never rewrite text).
   Caveat: if pass-1 already produced "Charles de ville," logprobs can't
   resurrect "Charlottesville" — this reinforces borderline entities, it
   doesn't raise the dead.

## Design exploration: the personal + register prior *(live, evolving)*

This is the dict-seed EPIC's (#54) missing half — the answer to "how do we bake
in knowledge of 'rare words' and 'uniquely yours'?"

### Two priors, not one
- **Shared register prior** — what *our ICP* says (`API`, `deploy`, `ship`,
  `staging`). Population-level, ships with the app, works on day 0.
- **"Uniquely yours"** — your project names, colleagues, jargon. Personal,
  grows from your history (already mined: `vocab suggest`, the dict-seed EDA).

### The one score that separates signal from noise
```
distinctiveness(w) = freq(w | your speech OR tech-register) ÷ freq(w | general French)
```
- `API` → high in tech, ~0 in general FR → **high ratio → bias it**
- `le`, `de` → high everywhere → ratio ≈ 1 → ignore (stopword)
- `épiailles` → ~0 *everywhere* → **the tell of a misfire, not a word**

The last line is the gift: OOV-everywhere + adjacent to a high-ratio tech term =
**suspected corruption** → auto-nominate `épiailles→API` for the lexicon (#31),
after it recurs (the "caught red-handed twice" bar).

### Offline "once" sources — frequencies are facts, not corpora
You derive a frequency *table* from a corpus without shipping the corpus (a
count isn't copyrightable; share-alike on the source text doesn't follow).
Build-time, fetch-once:
- **`wordfreq`** (Robyn Speer) — precomputed Zipf freqs, FR + EN, blended
  corpora. The general-language denominator, offline. `zipf("épiailles","fr")≈0`.
- **Lexique 3** (FR, CC-BY) / **SUBTLEX** (FR+EN subtitle freqs) — richer FR.
- **Tech-register numerator** — no off-the-shelf "FR-EN dev speech"; derive it
  (Stack Overflow dump, GitHub commit/issue text, HN → term frequencies) or
  bootstrap from a curated tech seed + each user's own codebase EDA (#54/#68).

**Doctrine ("own the spine, rent the algorithms," "quarantine heavy deps"):**
`scripts/build_register_prior.py` pulls the heavy deps *at build time* and emits
one small baked artifact — `data/register_prior.json` (top-few-thousand tech
terms + their log-ratio). The runtime ships only the JSON, zero deps.
Optionally ship `wordfreq` as a light runtime extra for live distinctiveness on
arbitrary personal words; degrade to a baked common-words set if absent.

### Cashing the #54 promise: RRF over three time-horizons
The 224-token tail forces ranking — top-K only. Fuse ranked signals with
**Reciprocal Rank Fusion** (the "RRF signal fusion" #54 already names):

| Horizon | Signal | Source | Helps |
|---|---|---|---|
| **Cold** (day 0) | register prior | baked `register_prior.json` | greenfield — `API` > `épiailles` |
| **Warm** | personal TF-IDF | history × wordfreq IDF | your jargon/project/colleagues |
| **Hot** (this take) | live entities | open project / clipboard (#70/#71) | the doc you're dictating about |

RRF → top-K → tail-loaded per #68. Bias stays **advisory** — a wrong prior just
fails to help, it *cannot* corrupt text. That's why pre-seed is safe where
post-correct is forbidden — and why it must be **measured** against #69 first.

### Baking it into stats/obs/analytics (nearly free)
- **"Ton vocabulaire distinctif"** — a new Analytics view: your terms ranked by
  `personal-TF × wordfreq-IDF`. The words uniquely yours; doubles as the
  seed-candidate list *and* a "here's your dialect" feature.
- **Suspected-misfire flags** — OOV-everywhere + adjacent-to-high-ratio-tech →
  surface as lexicon candidates (#31), recurrence-gated.

The history DB already holds the raw material; this is a scoring layer, not new
capture.

## Backlog seeded by this note
- **Entity-aware seeding & intra-take consistency** (#54 child) — logprob/NER-
  located spans → contextual bias + within-take canonicalization; gazetteer
  opt-in. Blocked on #69 (measure before trust).
- **Register + personal-distinctiveness prior** (#54 child) — bake offline
  freq table, TF-IDF distinctiveness, RRF-fuse cold/warm/hot into the 224-tail;
  "Ton vocabulaire distinctif" analytics + misfire flagging (feeds #31).
  Blocked on #69.
- Corpus grown by 4 cases (await WAV-regen + GPU run, #52).
