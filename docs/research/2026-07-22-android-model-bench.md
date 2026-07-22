# On-device whisper model bench — picking the Android daily default (#13)

**Date:** 2026-07-22 · **Device:** Fairphone 6 (arm64, Dimensity 7300, CPU only)
· **Issue:** [#13](https://github.com/PLNech/TuParles/issues/13)

## Context

The Android app bundles `ggml-base` (f16). Issue #13 framed the model choice as a
ladder with a hole in the middle: `base` is fast but fumbles tech vocab
(~1.5s per 4s clip, misses like "fan out" → "fais un air"), `large-v3-turbo` is
effectively flawless but slow (30-44s per clip). Everything between `base` and
`large-v3-turbo` was untested on the real target. This bench fills that gap:
six models decoded on the phone against the committed FR/EN code-switch corpus,
measuring decode wall time and transcript quality.

## Method

- **Models:** `tiny-q5_1`, `base-q5_1`, `base` (f16, current bundle),
  `small-q5_1`, `small` (f16), `medium-q5_0` — from
  [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp).
- **Clips:** n = **8** code-switch clips per model (48 decodes total), from the
  committed corpus (`tests/data/codeswitch/`), 16 kHz mono PCM16, neural (piper)
  TTS, 4 French-accent + 4 English-accent, spanning en-verb-borrow, homophone,
  acronym, numbers-switch, mid-sentence-switch and compound-borrow cases.
- **Engine:** a standalone `whisper-cli` built from the vendored whisper.cpp
  **1.9.1**, using the **same decode params as the app's JNI path** (`jni.c`:
  GREEDY, `no_context`, `language=auto`).
- **Build flags — the fidelity choice that matters:** NDK 27.1.12297006,
  arm64-v8a, **Release / -O3** (a -O0 ggml build is 10-50x slower), and
  `-march=armv8.2-a+fp16` to **mirror the shipping app exactly**. We deliberately
  did **not** enable `+dotprod`, because the app does not ship it. That decision
  turns out to dominate the results (see below).
- **Timing:** on-device wall clock (`date +%s%N`, delta via on-device `bc` — the
  device shell does 32-bit arithmetic and overflows a 19-digit nanosecond epoch).
  `THREADS=4`, fixed across models for a fair comparison.
- **Quality:** the repo's own scorer (`tuparles.eval.score_case`): the slot check
  (must-contain tokens present, must-not-contain absent) is the gate; word error
  rate ([WER](https://en.wikipedia.org/wiki/Word_error_rate)) is the trend. We
  score the **raw** engine output (no desktop `pipeline.postprocess`), since the
  Android engine has no such Python post-step. `xRT` = decode time ÷ audio length
  (lower is faster; <1 is faster than real time).

## Results

| model | size | mean ms | median ms | ms sd | mean xRT | slot pass | mean WER | WER sd |
|---|--:|--:|--:|--:|--:|:--:|--:|--:|
| tiny-q5_1 | 31 MB | 3215 | 3388 | 391 | 0.91 | 2/8 (25%) | 0.625 | 0.20 |
| base-q5_1 | 57 MB | 6062 | 6406 | 782 | 1.74 | 1/8 (12%) | 0.613 | 0.23 |
| **base-f16** (current) | 142 MB | 3211 | 3223 | 134 | 0.92 | 1/8 (12%) | 0.608 | 0.25 |
| small-q5_1 | 182 MB | 20293 | 20694 | 1654 | 5.79 | 2/8 (25%) | 0.532 | 0.23 |
| **small-f16** (pick) | 466 MB | 11953 | 12189 | 1214 | 3.41 | 3/8 (37%) | 0.523 | 0.25 |
| medium-q5_0 | 515 MB | 61981 | 61860 | 7823 | 17.74 | 3/8 (37%) | 0.491 | 0.22 |

![Quality vs speed, one bubble per model](img/2026-07-22-android-model-bench.png)

## Reading the numbers — what is signal, what is noise at n=8

- **Speed ordering is hard signal.** The per-clip spread is small (ms sd is a few
  percent of the mean), the ordering is stable across all 8 clips, and the gaps
  between models are large multiples. Trust the speed numbers.
- **The WER *gradient* (tiny → small → medium) is signal; adjacent-model WER gaps
  are noise.** WER sd is ~0.20-0.25 at n=8 — larger than the ~0.02-0.10 gap
  between neighbouring rows. So "medium (0.491) beats small-f16 (0.523)" is
  **not** a distinguishable difference at this sample size; "small beats base by
  ~0.08" is a real, monotonic trend but its margin is soft. Report it as a
  direction, not a decimal.
- **Absolute slot pass-rates are low (12-37%) and coarse.** We score raw output
  against an adversarial homophone corpus with no lexicon/postprocess, so these
  are a *relative* stress signal between models, not the accuracy a user sees
  (the app's post-decode path lifts them). A 1-case move (1/8 → 2/8) is within
  noise. The safe read: small/medium clear the bar roughly twice as often as
  base — consistent with the WER trend, not independent confirmation.

## The headline finding: on this build, f16 beats quantized

The build ships `+fp16` but not `+dotprod`. Without the dot-product kernel, the
int8 path that q5 models rely on falls back to a slower route, while fp16 matmul
is hardware-accelerated. The result inverts the usual "quantized is faster and
smaller" intuition, consistently across both families and all 8 clips:

- `base-f16` is **~1.9x faster** than `base-q5_1` (3.2s vs 6.1s) at equal quality.
- `small-f16` is **~1.7x faster** than `small-q5_1` (12.0s vs 20.3s) at equal-or-
  better quality.

So on the **current app build**, `base-q5_1` and `small-q5_1` are strictly
dominated: slower than their f16 sibling for no quality gain. They should not be
offered until dotprod is enabled — at which point the ranking may flip entirely
(the biggest open follow-up, below).

## Recommendation

**(a) Daily-driver default: `small-f16`.** It is the sweet spot #13 was after —
the best measured quality (lowest WER, highest slot pass) at ~3.4x real time
(~12s for a ~3.5s clip), still usable for push-to-talk dictation. `medium-q5_0`
buys no distinguishable quality (WER gap within noise) for **5x** the latency
(~62s/clip), so it is not the daily driver. `base-f16` stays the fast, light
fallback — but it is exactly the model #13 complains about, so it should not
remain the *only* option. Per house doctrine this is **"a setting"**: `small-f16`
as the recommended default, `base-f16` one tap away for speed-first users on
weaker phones.

**(b) Download-picker lineup for the lean-APK work (#13 / app-weight goal).**
Ship a lean APK and let the user pull a model along a speed↔quality ladder,
dropping the dominated q5 rungs:

| rung | model | size | character |
|---|---|--:|---|
| fastest | tiny-q5_1 | 31 MB | roughest; near real time |
| light default | base-f16 | 142 MB | near real time; fumbles tech vocab |
| **recommended** | **small-f16** | 466 MB | best balance; ~3.4x real time |
| most accurate | medium-q5_0 | 515 MB | slow (~18x); for offline/batch |
| flawless | large-v3-turbo | ~547 MB | slowest; existing option |

(`tiny-q5_1` stays as a q5 rung because at tiny size there is no f16 sibling in
the lineup and its footprint is the whole point.)

## Open follow-ups

1. **dotprod A/B (highest priority).** The Dimensity 7300 (Cortex-A78/A55)
   supports dot-product. Enabling `-march=armv8.2-a+fp16+dotprod` in the app's
   JNI CMake should accelerate the q5 int8 path and could make `base-q5_1` /
   `small-q5_1` both faster *and* smaller than their f16 siblings — which would
   change this entire recommendation. Re-run this exact matrix with dotprod on
   and compare. This is the single most decision-relevant unknown.
2. **Thread-count sweep.** Fixed at 4 here. The 7300 is 4 big + 4 little; 6 or 8
   threads (or pinning big cores) may shift the speed numbers, especially for the
   larger models.
3. **Grow n and score post-processed output.** n=8 gives wide WER error bars.
   Add clips and also score through the app's post-decode path to estimate
   user-visible accuracy, not just raw-engine stress.

## Reproducing

Kit (scripts, built arm64 `whisper-cli`, models, clips, scorer, chart): see the
session's bench-kit. One command with the phone connected:
`./run-bench.sh && python3 score.py && python3 chart.py small-f16`. Total device
run: 48 decodes in ~15 min.
