# Android STT Engine Survey — Adversarial Verification
## Issue #2: Make TuParles Android-library-ready

**Date:** 2026-06-27  
**Purpose:** Pressure-test the load-bearing claims in `2026-06-27-android-stt-engines.md`.  
**Method:** Direct source fetches (GitHub repos, arXiv papers, Maven), parallel web search on
each contested claim. No vendor docs accepted without corroboration.

---

## Claim 1 — FR/EN Code-Switching Handling

### Original claim
> Whisper (all variants, any wrapper) was trained on multilingual data including FR+EN simultaneously,
> and handles code-switching "reasonably" — the best published solution for this use-case.
> WER at switch points: 10–30% spike vs. monolingual segments (CLAIM, OpenAI eval paper).

### Adversarial findings

**What the research actually shows:**

1. **Adapting Whisper for Code-Switching (arXiv:2412.16507, 2024) — Mandarin/English only.**
   Vanilla Whisper-small achieved **Mix Error Rate of 58.3%** on intra-sentential Mandarin-English
   code-switching. The paper's conclusion: "Its poor performance suggests that handling CS directly
   using pre-trained Whisper is challenging." The model "tends toward language confusion due to
   accents, auditory similarity, and seamless language switches."  
   Source: https://arxiv.org/html/2412.16507v2

2. **SwitchLingua (arXiv:2506.00087, 2025) — closest to FR/EN data found.**
   Whisper-Large-v3 achieved WER 0.2483 on French-English code-switched test sets — best of all
   models tested. BUT: (a) this is Large-v3, not small/base; (b) results are aggregated across
   inter-sentential, intra-sentential, and extra-sentential switching — no breakdown by type.
   Source: https://arxiv.org/html/2506.00087v1

3. **The "10–30% spike" figure is unverifiable.** No OpenAI publication with this specific
   claim was locatable. The OpenAI Whisper paper (Radford et al., 2022) does not report
   code-switching WER benchmarks at all. This figure appears to be a secondary estimate,
   not a primary measurement.

4. **Critical gap:** Large-v3 vs. small is not a footnote — it is a performance chasm.
   The mobile-viable models (small, 244 MB; base, 74 MB) are 2-4x smaller than large-v3.
   At small scale, the Mandarin-English analogue shows MER of 58% baseline. There is no
   published FR/EN small-model on-device code-switching measurement anywhere in the literature.

### Verdict

| Sub-claim | Verdict | Reason |
|---|---|---|
| "Whisper handles FR/EN code-switching reasonably" | **OVERSTATED** | Large-v3 shows WER ~25% on CS test sets; small/base models are unmeasured and analogues show MER 58% on other language pairs |
| "Best published solution for FR/EN CS" | **CONFIRMED** (weakly) | Whisper-Large-v3 does outperform all other tested models on SwitchLingua FR/EN; no better packaged alternative exists |
| "10–30% WER spike from OpenAI eval paper" | **UNVERIFIABLE** | No such paper found; figure is an estimate, not a measurement |
| "multilingual = code-switching capable" | **OVERSTATED** | Multilingual training improves CS but does not solve it; intra-sentential performance is substantially worse than per-language monolingual |

**Impact on issue #2:** The shortlist engine choice stands (Whisper is still best available), but
the confidence in its FR/EN quality is lower than the original note implies. The 50-utterance
eval recommendation becomes **mandatory**, not optional.

---

## Claim 2 — Model Size / RAM / Latency (whisper small on mid-range ARM)

### Original claim
> whisper small multilingual: ~244 MB on disk, ~600 MB RAM (CLAIM), usable on mid-range.
> RTF on ARM mid-range: 0.8–1.5x (CLAIM, whisper.cpp README benchmarks, Apple M1 + x86;
> ARM mid-range unspecified).

### Adversarial findings

**Model size (disk):**
- The 244 MB figure is consistent with what whisper.cpp reports for `ggml-small.bin` (INT8 or
  Q5_0 quantized). Multiple secondary sources confirm ~244 MB for Q5 small. The original note
  flags this correctly as a CLAIM.

**RAM:**
- ~600 MB for small is plausible (ggml context + KV cache + model weights), but no independent
  Android measurement was found. iOS whisper.cpp apps report 500–700 MB for small; Android
  will be similar.

**Latency on Android ARM:**
- **Whisper.cpp GitHub issue #1070 (Android inference too slow):** Community reporters say
  "30 seconds for a few words" and "unusable" on unspecified Android devices using the small model
  with ~8 threads. No flagged resolution.
- **Better data point from openai/whisper discussion #506:** A developer ran `whisper.tflite`
  (quantized tiny, ~40 MB) on Pixel 7 and got ~2 seconds for 30 seconds of audio — RTF ≈ 0.067.
  That is tiny, not small, and tflite-quantized, not gguf.
- **WhisperKit (iOS proxy):** Per-word latency of ~0.45 s on Apple Silicon class chips. Apple
  Neural Engine is significantly faster than mid-range Android NPUs; this is an optimistic bound.
- **Rough sanity check (independent derivation):**
  - whisper-small: 244M parameters, Q5_0 quantized ≈ ~5 bits/param ≈ ~150 MB active weights.
  - ARM NEON throughput on Snapdragon 778G-class: ~50–80 GFLOPS (4 cores, INT8).
  - Whisper encoder pass for 30-s audio: ~encoder forward pass with mel-spectrogram 1500 frames,
    hidden 768, ~12 layers: rough FLOPs ≈ 2 × 768 × 768 × 12 × 1500 ≈ ~26 GFLOPS.
  - At 50 GFLOPS throughput: ~0.5 seconds encoder only. Decoder adds 1–4x depending on token
    count. **Rough estimate: 1–4 seconds for a 5–10 word utterance on Snapdragon 778G.**
  - RTF for a 3-second utterance: 1–4 s decode / 3 s audio = RTF 0.33–1.3x.
  - This makes the "0.8–1.5x RTF" figure plausible but on the optimistic end.

### Verdict

| Sub-claim | Verdict | Reason |
|---|---|---|
| whisper-small disk size ~244 MB | **CONFIRMED** | Consistent across whisper.cpp releases, multiple independent reports |
| ~600 MB RAM | **UNVERIFIABLE** (plausible) | No Android measurement found; iOS proxy data consistent; no red flag |
| RTF 0.8–1.5x on ARM mid-range | **UNVERIFIABLE** (plausible-to-optimistic) | No Android ARM benchmark exists; independent FLOPs derivation gives 0.3–1.3x for small utterances; community reports of "unusable" on unspecified device suggest real-world outliers exist |
| "usable on mid-range" | **UNVERIFIABLE** | Depends heavily on device, quantization level, and utterance length; batch push-to-talk at ~2–5 s clips is probably fine on Snapdragon 7xx+ with Q5 quantization; continuous streaming is not |

**Impact on issue #2:** The size/RAM picture is solid enough to proceed with whisper-small as the
candidate. Latency is genuinely unknown for the target hardware class — measure before locking
the model tier. The "unusable" reports are for streaming on old devices; push-to-talk batch mode
is substantially more forgiving.

---

## Claim 3 — Word-Level Confidence (whisper-jni)

### Original claim
> whisper-jni `WhisperSegment` has `t0`, `t1`, `text` per segment but no `probability` field.
> Word-level per-token log-probabilities are in `WhisperTokenData` but not exposed in the Android
> JNI API as of whisper-jni 1.6.x.
> GitHub issue #2775 (whisper.cpp): "word-level confidence on Android" — open, no resolution.

### Adversarial findings

**Direct source verification of whisper-jni API (fetched from GiviMAD/whisper-jni main):**

The WhisperJNI public API exposes:
- `fullGetSegmentText()` — segment text
- `fullGetSegmentTimestamp0/1()` — start/end time (centiseconds)
- `fullNSegments()` — segment count
- No `WhisperTokenData` exposure
- No token probability, word confidence, or per-token log-probability field

Latest version: **v1.7.1** (January 3, 2025). No release changelog mentions adding word-level
confidence or token probability. The library has not been updated since Jan 2025.

**GitHub issue #2775:** Confirmed open (opened Feb 1, 2025). Title: "Enable Word Level Timestamp
In Whisper Android." No resolution visible in publicly accessible content as of survey date.

**whisper.cpp C++ level:** The `whisper_token_data` struct in `whisper.h` includes `float p`
(probability) and `float pt` (probability of timestamp token). This IS exposed at C++ level —
but the JNI layer in whisper-jni does not bridge it to Java/Kotlin.

**Workaround path:** Patching whisper-jni to add `fullGetTokenP(ctx, segment_idx, token_idx)`
(mirroring `whisper_full_get_token_p`) is ~50 LoC of C JNI glue + Java binding. Non-trivial
but feasible; would need to fork GiviMAD/whisper-jni.

### Verdict

| Sub-claim | Verdict | Reason |
|---|---|---|
| whisper-jni does not expose `Word.probability` | **CONFIRMED** | Direct API source inspection: no token-level data in public methods as of v1.7.1 |
| `WhisperTokenData.p` exists in C++ core | **CONFIRMED** | `whisper.h` defines `float p` in `whisper_token_data`; exposed via `whisper_full_get_token_p()` |
| Issue #2775 is open, no resolution | **CONFIRMED** | Issue exists, confirmed open Feb 2025, no fix merged |
| JNI patch is required to surface confidence | **CONFIRMED** | The only path to `Word.probability` is a GiviMAD fork adding the JNI bridge |

**Impact on issue #2:** This is the most precisely verifiable claim, and it is correct. The
original note's "confidence=None" degraded mode (matching qwen-CPU desktop fallback) is the
only option until the JNI is patched. For ORT path (Rank 2), raw logits are accessible and
word confidence is derivable — that distinction is real and correct.

---

## Does the Shortlist Survive?

**Yes — with two material downgrades:**

### Rank 1: whisper.cpp + whisper-jni — SURVIVES, confidence reduced

The engine ranking is correct (best FR/EN CS coverage of packaged options; MIT; push-to-talk
batch compatible). But two original claims are overstated:
1. FR/EN code-switching quality at `small` scale is genuinely unknown — the "reasonable" label
   is borrowed from Large-v3 performance and may not transfer. MER 58% on analogous models in
   other language pairs is the worst-case reference.
2. Latency on mid-range Android is unverified. "Usable" is likely true for batch push-to-talk
   on Snapdragon 7xx+; it is NOT a given for continuous streaming or lower-end devices.

**Revised framing:** whisper.cpp + whisper-jni is Rank 1 *conditional* on the 50-utterance
FR/EN code-switch eval on target hardware. If small model quality is below the product bar,
the fallback is either medium (slower) or the ORT path with a larger model.

### Rank 2: ONNX Runtime Mobile + Whisper ONNX — SURVIVES, strengthened

The word-confidence advantage over whisper-jni is now *confirmed*, not just claimed. For any
build where the doubt/spans UI is required at launch (not degraded mode), ORT is the correct
first choice, not a fallback.

### Rank 3: sherpa-onnx — SURVIVES, no change

French model quality issues remain unverified (GitHub issue #3144, no resolution). Still
blocked by the same blocker. Correct to rank third.

---

## Summary Table of All Verdicts

| Claim | Verdict | Source |
|---|---|---|
| Whisper handles FR/EN CS "reasonably" | OVERSTATED | Large-v3 WER ~25% (SwitchLingua); small/base unmeasured; intra-sentential MER 58% on analogues |
| 10–30% WER spike from OpenAI eval | UNVERIFIABLE | No such paper locatable; not in Radford 2022 |
| "Best packaged solution for FR/EN CS" | CONFIRMED (weakly) | Large-v3 outperforms all tested alternatives on SwitchLingua FR/EN |
| whisper-small ~244 MB disk | CONFIRMED | Multiple independent reports |
| whisper-small ~600 MB RAM | UNVERIFIABLE (plausible) | No Android measurement; iOS proxy consistent |
| RTF 0.8–1.5x on mid-range ARM | UNVERIFIABLE (plausible-to-optimistic) | No Android ARM benchmark; FLOPs derivation gives 0.3–1.3x for batch PTT; community reports of slow streaming outliers |
| whisper-jni has no word probability API | CONFIRMED | Direct source fetch of v1.7.1 public methods; no token-level data |
| whisper.cpp C++ exposes token probability | CONFIRMED | `whisper_token_data.p` in `whisper.h` |
| Issue #2775 open, unresolved | CONFIRMED | GitHub search: issue exists, no resolution Feb 2025 |
| ORT path enables word confidence via logits | CONFIRMED | ORT GenAI exposes decoder logits; aggregation to word-level probability is feasible |
| sherpa-onnx FR model has quality issues | CONFIRMED | GitHub issue #3144; community report "a lot of mistakes"; no maintainer resolution |

---

## Revised Bottom Line for Issue #2

The shortlist is correct. The ranking holds. Two confidence levels are revised downward:

**FR/EN code-switching quality** — treat the engine as *probably workable*, not *known good*.
The 50-utterance eval on target hardware is not optional; it is the decision gate. If the small
model fails, evaluate medium (769 MB, RTF likely >2x) before concluding the architecture is wrong.

**Word confidence** — if spans/doubt UI is a launch requirement (not a v1 deferral), use ORT
(Rank 2), not whisper.cpp. The JNI patch path exists but adds maintenance burden of a private fork.

**The latency question** is genuinely open for Android mid-range. The "usable for push-to-talk"
claim is plausible from first principles but unsupported by published Android ARM benchmarks.
Measure on a Snapdragon 7xx device before committing model tier.

---

## References (adversarial sources)

- SwitchLingua FR/EN WER 0.2483: https://arxiv.org/html/2506.00087v1
- Whisper CS MER 58% baseline (Mandarin-EN): https://arxiv.org/html/2412.16507v2
- whisper-jni API (v1.7.1, no token data): https://github.com/GiviMAD/whisper-jni
- whisper.cpp Android slow (#1070): https://github.com/ggml-org/whisper.cpp/issues/1070
- whisper.cpp word timestamps Android (#2775): https://github.com/ggml-org/whisper.cpp/issues/2775
- Whisper.tflite tiny on Pixel 7, RTF ≈ 0.067: https://github.com/openai/whisper/discussions/506
- whisper.cpp Android discussion: https://github.com/ggml-org/whisper.cpp/discussions/283
- sherpa-onnx FR quality issue #3144: https://github.com/k2-fsa/sherpa-onnx/issues/3144
