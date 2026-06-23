# Codebase-aware dict-seeding: building the engine, and what the corpus told us

*Build note, 2026-06-24. Seeds the blog (#42). Companion data:
`docs/research/data/2026-06-24-nlp-eda*.json`; engine in `src/tuparles/nlp/`.*

## Why

A real misfire started this: "fanout les agents" came back as *"toi tu fais un
air de jamais les agents"*. Whisper had never heard `fanout`; French phonetics
swallowed it. The pattern generalises - **the words you dictate at your machine
are the words that live in your code** (`RequestOptions`, `faceting`,
`getFacetValues`), and they are precisely the out-of-vocabulary tokens an STT
model mangles. So: mine the codebase, find those words, and bias the decoder
toward them (#54). This note is the first time the engine actually ran on real
corpora - TuParles itself and AlgoliaSaaS (a large C++/Python service).

## What we built (own the spine, rent the algorithms)

No single NLP library fits, because our problem spans two worlds. Code, where
`getFacetValues` must survive intact and *where a token appears* (a dependency
name vs an H1 vs a comment) is the signal - spaCy's tokeniser would split the
camelCase and lemmatise away the exact form we need. And prose (chat history,
transcripts), where the standard tools shine. So we **own the thin spine** - a
typed-term `Document` and AST extraction - and **rent the rest**: TF-IDF and
clustering from scikit-learn, keyphrases from YAKE, embeddings from fastembed.

The pipeline is source-agnostic:

```
sources (code / text / chat)  →  Document = (id, source, typed-term stream)
Corpus.ingest                 →  per-term features (count, salience, by SrcType…)
Corpus.compute_metafeatures   →  peak TF-IDF (scikit-learn)
signals + fuse                →  symbol / tfidf / embed rankers, fused by RRF
engines.{dictseed,keywords,cluster}
```

The heart is a **hierarchical weight table**: a dependency name scores 10, a
def/class name 6, an H1 5, a used identifier 3, a comment word 1. That table is
the whole idea, so it lives in one readable place (`nlp/parse.py`). Dict-seeding
is just one engine on top; keyword/tag-cloud and clustering ride the same core,
over code or chat history alike.

## What the corpus told us

Run over **TuParles (79 mineable files) + AlgoliaSaaS (2,756)**: **51,652
unique terms, 39,342 candidates** (seen ≥2×).

### 1. The noise filter earns its keep

| repo | tracked | mineable | dropped |
|---|--:|--:|--:|
| TuParles | 96 | 79 | 17 (18%) |
| AlgoliaSaaS | 8,169 | 2,756 | **5,413 (66%)** |

Two-thirds of AlgoliaSaaS's tracked files are dictation noise: 4,470 generated
fixtures/logs/binaries (`.cmd`/`.res`/`.check`/`.log`) + 943 data files. Mining
git-tracked files (free `.gitignore` respect) **and** a kind filter is not
optional at this scale - and we *count* every drop, never swallow it silently.

### 2. Raw salience is volume-biased

Where does the summed salience actually come from?

| SrcType | share |
|---|--:|
| code_ident (coarse C++ sweep) | **72.9%** |
| comment | 17.4% |
| ident / md_prose | ~3.5% each |
| def_name | 0.4% |
| **dep** | **0.0%** |

Dependency names carry the *highest per-occurrence* weight (10) but there are so
few of them that they vanish in the total, while the sheer mass of C++
identifiers dominates. **Salience-by-volume is not the same as importance** - a
lesson with teeth, see next.

### 3. The bombshell: symbol and TF-IDF rank *completely* different vocab

Top-15 by raw salience vs by TF-IDF distinctiveness - **overlap: 0/15.**

| by salience (symbol) | by distinctiveness (tfidf) |
|---|---|
| `const`, `std`, `if`, `the`, `return` | `GeoRecord`, `readBinKeys`, `Airport` |
| `size_t`, `include`, `auto`, `void` | `scheduledJobs`, `idxCompiler`, `FACE` |

The symbol signal alone is **garbage at scale**: it surfaces C++ keywords and
English stopwords, because they occur the most. TF-IDF rescues it by
down-weighting what's everywhere and surfacing what's characteristic of *this*
code. This is the empirical justification for the whole multi-signal design:
neither signal is trustworthy alone.

### 4. The signals are genuinely independent → RRF is the right fusion

Pearson correlations across all 39k candidates:

- salience ~ tfidf: **+0.03**
- salience ~ risk: −0.06
- tfidf ~ risk: +0.15

Near-zero. Fusing correlated signals is pointless; these carry independent
information, which is exactly when Reciprocal Rank Fusion pays off. (Boring,
calibration-free, robust to one signal being noisy - innovation tokens spent
elsewhere.)

### 5. whisper-risk cleanly separates code from language

Mean risk: **identifiers 0.63 vs prose 0.10.** The transparent additive
heuristic (camelCase +0.40, snake_case +0.35, ALLCAPS +0.30, digits +0.20,
accented-real-word −0.20) does what it should - and it's a heuristic we can tune
against the FP/FN harness (#69), never a black-box confidence score.

### 6. The payoff: the fused, risk-gated seed list is *sane*

`seed_score = RRF(symbol, tfidf) × (0.25 + 0.75·risk)` produces real dictation
targets from the noise: **`GeoRecord`, `fromUTF8`, `idxCompiler`, `readBinKeys`,
`scheduledJobs`, `currentUserKey`, `partialUpdateOk`, `content_type`.** On a
TuParles-only run the same machinery surfaces `apply_lexicon`,
`decode_language_opts`, `resolve_device_index` - exactly the words we fumble
when dictating to Claude.

## Decisions this drives

1. **min_count + RRF + risk-gate are load-bearing**, not nice-to-haves. Symbol
   salience alone is unusable on a real codebase; the fusion is the product.
2. **We need a framework/stopword filter.** Test macros leak hard -
   `CPPUNIT_ASSERT` has salience 19,031 (the single largest) and survives into
   the seed list on ALLCAPS-risk. A small per-language stoplist + a "looks like
   a test/framework symbol" demotion is the next tuning pass (#69). Likewise,
   TuParles-only runs leak pytest fixtures (`tmp_path`, `monkeypatch`).
3. **Per-occurrence salience normalisation** is worth trying - raw Σ is
   volume-biased toward big C++ files; a length/volume normaliser would let the
   high-weight-but-rare dep names matter again.
4. **The coarse C++ sweep is noisy but TF-IDF tames it.** tree-sitter would give
   real hierarchy (def vs use) per language - noted, deferred (YAGNI for v1).
5. **Everything is a setting** (the standing principle): corpus selection,
   min_count, the weight table, signal weights, risk coefficients - all knobs,
   all gated by the FP/FN harness before they earn the decoder's trust.

## The embedding comparison (#66)

We compare three lenses for the *semantic* signal: TF-IDF (lexical), symbol
(structural), and embeddings (neural). Backend is pluggable so we can compare
models: **fastembed** (ONNX, CPU-native, no torch - the lean one we'd actually
ship; multilingual MiniLM-L12) runs here; **sentence-transformers** is wired but
deferred to a post-reboot session (its torch wouldn't import on this
CUDA-wedged box - documented, not hidden).

<!-- EDA-EMBED-START -->
**fastembed ran** (multilingual MiniLM-L12, top-4,000 distinctive candidates -
embedding 39k mostly-noise C++ tokens adds little and we say so, not silently).
Two findings:

**The embedding is near-orthogonal to the other signals.** Spearman rank
correlation of the embedding ranking against the others: **vs symbol +0.08, vs
TF-IDF −0.02.** Almost no overlap - it carries genuinely independent
information, which is the empirical license to fuse it as a third RRF signal
rather than as a redundant tie-breaker.

**Clustering isolates the noise for free.** KMeans (k=10) over the embeddings
produced coherent *domain* themes - and, unprompted, quarantined the noise:

| theme | sample members |
|---|---|
| index settings | `idxCompiler`, `indexSettings`, `SearchTimeouts`, `clusterName` |
| keys / ACL | `readBinKeys`, `currentUserKey`, `UserKeyACL`, `addKeyValue` |
| UTF / low-level | `fromUTF8`, `toUTF8`, `uint16_t`, `x80` |
| tokenizer config | `normalizerConfiguration`, `tokenizerConfiguration` |
| **test macros (noise)** | `CPPUNIT_ASSERT`, `STRING_COMPARE`, `ALGOLIA_ASSERT_ERROR_OK` |
| **test fixtures (noise)** | `expectedValue`, `expectedCode`, `expectedMessage`, … |

The same mechanism that surfaces the vocabulary a user *dictates about* (index
settings, keys, encoding) also collapses the framework macros and `expected*`
fixtures into their own clusters. That is a real decision: **cluster-based
denoising** - drop or down-weight the test/assert cluster - is a cheaper, more
robust path to the "framework noise" problem than a hand-maintained stoplist,
and it falls straight out of the embedding signal we already compute.
<!-- EDA-EMBED-END -->

## Tooling, while we were here

Adopted the 2026 quality baseline: **mypy** (CI gate, Qt frontend grandfathered),
**pytest-cov**, **pre-commit**, stricter **ruff** (I/B/UP/SIM/C4/RUF). Heavy
embedding deps are quarantined in an optional `embed` group so the cross-OS CI
matrix never touches torch; their tests carry an `embed` marker, deselected by
default - same pattern as the `gpu` marker.

> *Mesure deux fois, coupe une fois* - measure twice, cut once. The corpus had
> opinions; we listened before tuning.
