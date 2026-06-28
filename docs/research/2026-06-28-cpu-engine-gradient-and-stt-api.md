# CPU engine gradient + the `/stt/` API — porting Android wins, planning the cloud

*2026-06-28. Two questions: can the Android acceleration work feed back into the
desktop CPU path, and can TuParles' STT be exposed as `api.nech.pl/stt/v1/`?
This note is the why behind the answers. No code shipped — recon + design.*

## 0. The worktree wasn't a lost repo

`TuParles-android` looked like an orphan checkout (no `.git` dir). It was a **git
worktree** of this repo on `feat/android-spike`, and that branch was **already
merged into `main`** (merge `bc12fc4`, "Android experimental POC (#2)"). `android/`
has lived on `main` since. The worktree held only re-fetchable model blobs +
build artifacts, so it was retired (`git worktree remove`; local branch deleted;
`origin/feat/android-spike` + `origin/feat/android-core-config-split` left on the
remote). Lesson: a `.git` *file* (not dir) = worktree; check `git worktree list`
before assuming a repo went missing.

## 1. Android → desktop CPU: mostly learnings, one real port

The two headline Android breakthroughs don't port — because the desktop already
solved their root causes a different way:

| Android win | Ports to desktop? | Why |
|---|---|---|
| `-O3` fix (58.7×, debug `-O0` trap) | Learning only | desktop uses prebuilt wheels + a vendored binary, no `-O0` trap. But see the build-flag audit below. |
| `language=auto` not hardcoded `"en"` | Already done | CPU partials detect language per 20s window (`config_core.py`, short *to track switches*). |
| NNAPI / Hexagon / FP16 ARM delegates | N/A | no NPU on a laptop; its accelerator is the CUDA GPU, already primary. |

**The one real port: adopt whisper.cpp as the CPU engine.** Today there's a
quality/feature cliff between paths — GPU runs faster-whisper `large-v3-turbo`
(29× RT, `initial_prompt` vocab-biasing, per-word confidence), while the CPU
fallback is vendored `qwen-asr 0.6B` (2.7× RT, **no prompt support, no word
confidence, a different model family**). The Android port proved whisper.cpp
(GGML, quantized) runs `large-v3-turbo-q5` at *flawless* FR/EN quality and it's
already vendored + building in `android/whisper/`. Bringing it to the desktop CPU
path would close the regression (restore prompt-bias + word-confidence on CPU),
unify the model family GPU↔CPU, and offer a CPU quality/speed tier choice. Whether
it beats qwen on *speed* at equal quality is the open empirical question — hence
the benchmark (Task #3). Smaller cheap carries: a **build-flag audit** (the `-O3`
lesson generalized — confirm the vendored `qwen_asr` and ctranslate2 use the SIMD
they should), and **reuse of the Android FR/EN corpus** as a CPU-path regression
eval.

## 2. The progressive-enhancement gradient

The house doctrine — *"every feature degrades gracefully, GPU-or-CPU never
GPU-or-nothing, chooses at runtime by what is actually available"* — already
defines a 2-rung ladder (turbo-GPU / qwen-CPU). This widens it into an N-rung
gradient along a realistic **VRAM (GPU) → RAM + AVX-level + cores (CPU)** axis.
**The engine flips at the GPU boundary**, and one weight family
(`large-v3-turbo`) spans rungs 2-5 so only quant/runtime change, not behaviour:

| Rung | Hardware | Engine | Model | Quant | Footprint | ~RTF |
|---|---|---|---|---|---|---|
| 0 Emergency CPU | erable i3-2130 (no AVX2, ~1.8GB) | whisper.cpp | tiny | q5_0 | ~150MB | ~1× (short only) |
| 1 Light CPU | modest VPS / home box (AVX2, 4-8GB) | whisper.cpp | base | q5_0 | ~400MB | ~0.3-1× |
| 2 Strong CPU | laptop i9-13900H (14 P-core) | whisper.cpp | large-v3-turbo | q5_0 | ~1.5GB | ~1× *(benchmark)* |
| 3 Low-VRAM GPU | 2-4GB (GTX 1650, T4 slice) | faster-whisper | small/base | int8 | ~1-2GB | 5-10× |
| 4 Mid-VRAM GPU | 6-8GB | faster-whisper | large-v3-turbo | int8_float16 | ~3-4GB | 15-25× |
| 5 High-VRAM GPU | RTX 4080 16GB (today) | faster-whisper | large-v3-turbo | float16 | ~1.6GB | 29× |

Design points:
- **Selection probe** mirrors `capability.py`'s "probe once, report one line,
  degrade explicitly": CUDA + VRAM → else AVX-level + free-RAM + cores → pick the
  highest affordable rung. *It's a setting*: auto-default + Réglages override.
- **whisper.cpp is the unifier** — musl-friendly (alpine), AVX2-graceful, light
  deps, same GGML weights across Android / erable / home-box / laptop-CPU.
  ctranslate2 stays GPU-only (no musl wheels, best GPU throughput).
- **qwen-asr is on the ballot**: retire it if whisper.cpp wins Task #3 at
  equal/better quality; keep only if it's materially faster somewhere.

## 3. The `/stt/` API on api.nech.pl

- **Domain `/stt/`** (TuParles = frontend / internal name). The generic `audio`
  domain is taken — codename Douanier, owner ParVagues, `armada/api`, LIVE — so
  STT gets its own.
- **Tier = container, but thin.** erable can't host real inference (§4). Per the
  platform's own RECIPE doctrine ("don't load big models on the box; isolate the
  backend behind an env URL; 503 until a GPU runner exists"), the erable shim does
  auth/hash/cache/validate and **dispatches** to whatever rung is available.
- **Engine = whisper.cpp, NOT faster-whisper**, anywhere that touches the alpine
  base: ctranslate2 ships manylinux/glibc wheels only, no musl. whisper.cpp
  compiles clean on musl (the Android port proved the build). This is exactly why
  §1 and §3 want the same engine.
- **WAV-batch first; streaming deferred** to chunked-POST v2 (whisper.cpp
  streaming is broken/expensive on CPU — the qwen `--stream` finding from Sprint 1
  and the Android survey both say so).
- **Caching**: app-level `cache.get_or_set(sha256(wav))` (Redis), not edge
  `proxy_cache` (POST body isn't in the URI). STT is idempotent + expensive → big
  win. Scope: path-derived `api:stt:transcribe`.

## 4. erable reality (why dispatch, not on-box)

`erable.plnech.fr` is a **2011 Intel Core i3-2130** — 2 cores / 4 threads, **AVX1
only, no AVX2 / no FMA**, RAM 7.7GB but **~1.8GB available and already swapping**,
~8GB disk free, no usable GPU, kernel 4.9 / Docker 19.03. So: it can host the thin
shim fine; whisper.cpp **tiny** on short clips is the realistic ceiling; **base**
pushes it into swap; a 1.5GB model OOMs. The platform's no-big-models doctrine was
a measurement, not pessimism. The real STT muscle must live on a beefier rung (a
home box, or a future GPU runner) — *not* a laptop tunnel (rejected), *not* erable.

## 5. Shared cache layer (Redis) — not yet, but cheap

No Redis container runs on nech.pl; the `cache.get_or_set` helper falls back to a
**per-process in-proc dict** (unshared, lost on restart). But `redis-server` is
already installed on the host. Cheapest win: a **capped host Redis**
(`maxmemory 128mb`, `allkeys-lru`) pointed at by `NECHAPI_REDIS_URL`, no docker
tax — caution only because the box is RAM-tight, so cap it hard. Worth documenting
in PLATFORM.md / RECIPE.md for other contributors (deferred).

## 6. Can we benchmark with our own recordings?

Corpus = `tests/data/codeswitch/{corpus.json,wav/}` (ground-truth + WAVs) + qwen
English samples (5-119s) + `spike-test.wav`. The WAVs are **espeak/piper
TTS-synthesized**, not human. So:
- **Speed / RTF: yes, plenty** — decode time is audio-agnostic; the duration
  spread is ideal for RTF curves.
- **Quality / WER: relative ranking + regression only, not real-world WER** — TTS
  doesn't code-switch with natural prosody (precisely how the `language="en"` bug
  hid). Bootstrap on synthetic now; queue a small real-human FR/EN capture (reuse
  the Android 12-prompt harness) before locking a tier. The laptop **history DB**
  may hold real takes — gold if it retained audio (privacy permitting).

## Open decisions (for next session)

1. **Home-box (e.g. "domovoy") hardware specs** — unknown; needed to place rung 1-2.
2. **STT backend host**: erable-tiny+short-clip-cap v1 / stand up a home box as the
   dispatch backend / wait for a GPU runner and 503 until then.

*Measure before you trust — including the box. The honest gradient came from an
`ssh`, not an assumption.*
