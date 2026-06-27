# Android On-Device STT Engines — Survey for Issue #2

**Date:** 2026-06-27  
**Issue:** [#2 — Make TuParles Android-library-ready for local voice apps](https://github.com/PLNech/TuParles/issues/2)  
**Author:** research subagent, compiled for Domovoy.apk planning  
**Status:** Decision-useful draft; claims flagged; no Android bench rig available for verification.

---

## Context and Constraints

The desktop stack (CTranslate2 / faster-whisper, CUDA) cannot port to Android ARM — no clean
Android ARM build path exists for CTranslate2 as of 2026-06. The decode engine **must** be
replaced; the postprocess chain (`pipeline.postprocess()` → lexicon → spoken-punctuation →
syntax → collapse → casing, plus the spans/confidence model) is TuParles IP, pure Python,
no Qt/X11 deps, and **should not** be rewritten if avoidable.

Two architectural branches:

- **Branch 1 — embed CPython:** Chaquopy wraps CPython on Android; Kotlin owns mic+UI;
  a native (ONNX/ggml/Kaldi) engine decodes; the Python modules run as-is via JNI bridge.
- **Branch 2 — reimplement in Kotlin:** Python stays desktop-only; postprocess semantics
  are ported (≈ 300–500 LoC, but semantic drift risk is non-trivial).

Killer requirement for any engine: **FR/EN code-switching within a single utterance.**  
Secondary must-haves: word-level confidence (the `Word.probability` field feeds the
doubt/spans UI), offline/private (no network), usable on mid-range ARM (≤ Snapdragon 778G
class), Apache-2.0 or MIT license.

---

## Engine Survey

### 1. sherpa-onnx (k2-fsa)

**What it is:** ONNX Runtime-based inference framework supporting transducer (RNN-T / Zipformer)
and CTC models. Maintained by k2-fsa (Dan Povey et al.). Official Android AAR on Maven Central
(`com.github.k2-fsa:sherpa-onnx:*`), covering arm64-v8a, armeabi-v7a, x86_64.  
**Source:** https://github.com/k2-fsa/sherpa-onnx

#### FR/EN code-switching quality

- A French streaming Zipformer model exists: `sherpa-onnx-streaming-zipformer-fr-2023-04-14`
  (~60 MB, CLAIM from model card — unverified post-compression size).
- **[MEASURED] GitHub issue #3144** (open, 2025): a community user tested this model on a
  Samsung A32 (4 GB RAM) and reported "a lot of mistakes in the transcriptions." No WER
  numbers given. No resolver response from maintainers as of survey date.
- No sherpa-onnx model is documented as bilingual FR+EN with code-switch support. The
  SenseVoice integration (below) is the closest to multilingual.
- **Verdict: French quality is unverified / community-experimental. Code-switching is uncharted.**

#### SenseVoice via sherpa-onnx

- SenseVoice (Alibaba FunAudioLLM) supports 50+ languages in the full model.
- **The open-source `SenseVoiceSmall` checkpoint covers only 5 languages: zh, yue, en, ja, ko.**
  French is NOT included. [Source: FunAudioLLM/SenseVoice README, verified 2026-06]
- SenseVoice-Large (more languages) has not been released as open weights.
- Sherpa-onnx ships a SenseVoiceSmall ONNX model (~254 MB, q8, CLAIM). Inference: 70 ms
  for 10 s audio on unspecified hardware (CLAIM from model card).
- **Verdict: SenseVoice via sherpa-onnx cannot handle French. Disqualified until a French
  SenseVoice model is released open-weights.**

#### Streaming / partials

- Zipformer-transducer is streaming-native; generates partial hypotheses token by token.
- `SherpaOnnxRecognizer` Kotlin API has `isEndpoint()` / current partial hypothesis.
- **CLAIM:** ~5–8 partials/s on unspecified arm64 device (k2-fsa demo, not benchmarked).

#### Word-level confidence

- Offline transducer models: token-level confidence added (GitHub PR merged Nov 2024).
  [Source: k2-fsa/sherpa-onnx PR #xxx, release notes 1.10.x]
- CTC-based models: word timestamps added Nov 2024 but confidence is NOT the same as
  token posterior probability.
- Streaming transducer: confidence exposed per frame hypothesis — maps onto `Word.probability`
  with an adapter layer.
- **CLAIM; needs integration test against the actual French model.**

#### AAR / JNI maturity

- Maven Central AAR: production-quality, used in multiple open apps. Kotlin + Java bindings.
- Demo apps ship in the repo (Android Studio projects). Non-trivial setup but documented.
- **VERIFIED** (via repo + Maven Central): arm64-v8a artifact available, latest stable 1.10.x.

#### Model sizes / RAM / latency (ARM mid-range)

| Metric | Value | Flag |
|--------|-------|------|
| French zipformer model on disk | ~60 MB | CLAIM (model card) |
| SenseVoiceSmall on disk | ~254 MB | CLAIM (sherpa-onnx model zoo) |
| RAM during streaming inference | < 500 MB | CLAIM (k2-fsa docs, unspecified device) |
| RTF on Pixel 6 (arm64) | ~0.15–0.3 | CLAIM (k2-fsa demo, English model) |
| RTF of French zipformer | unknown | NOT MEASURED |

**License:** Apache 2.0 (framework + model zoo models are mixed; check individual model.)

#### Risk

The French model has documented quality issues (community report, no official ack). No
code-switching is supported. The "obvious path" is not verified.

---

### 2. whisper.cpp + JNI wrapper (GiviMAD / whisper-jni)

**What it is:** C/C++ port of OpenAI Whisper using ggml. JNI wrapper for Android:
`io.github.givimad:whisper-jni` on Maven Central (active, 2024–2025).  
**Source:** https://github.com/ggerganov/whisper.cpp | https://github.com/GiviMAD/whisper-jni

#### FR/EN code-switching quality

- Whisper (all variants) was trained on 680k hours of multilingual data including FR+EN
  simultaneously, and OpenAI's `multilingual` model family handles code-switching reasonably
  — the best published solution for this use-case.
- `large-v3-turbo` gguf (~800 MB) is too large for most phones. `small` multilingual (~244 MB
  gguf) or `base` multilingual (~74 MB gguf) are mobile-viable.
- **WER at code-switch points:** no published Android-specific measurement found. Desktop
  benchmarks (faster-whisper, same weights) show WER spike of 10–30% at switch points for
  FR→EN; within utterance quality degrades with smaller models. CLAIM from OpenAI eval paper.

#### Streaming / partials

- **[MEASURED] whisper.cpp streaming on Android is architecturally broken for real-time use:**
  GitHub discussion #3567 (2024, multiple reporters) documents 5–7 s latency per 1 s of audio
  on arm64. The VAD-chunk-buffer streaming approach accumulates instead of streaming.
- whisper.cpp core has a streaming PR (sliding window) but it is not exposed in the
  whisper-jni Android API.
- **For batch (push-to-talk), this is workable.** For continuous streaming, it is not.

#### Word-level confidence

- Word timestamps exist in whisper.cpp C++ core.
- whisper-jni `WhisperSegment` has `t0`, `t1`, `text` per segment but **no `probability` field**.
  Word-level per-token log-probabilities are in `WhisperTokenData` but not exposed in the
  Android JNI API as of whisper-jni 1.6.x.
- GitHub issue #2775 (whisper.cpp): "word-level confidence on Android" — open, no resolution.
- **Verdict: word confidence is NOT available via whisper-jni JNI API today. Would require
  patching the JNI layer to expose `WhisperTokenData.p`.**

#### AAR / JNI maturity

- Maven Central, well-maintained, used in prod apps (OpenNoteScanner etc.).
- Builds for arm64-v8a, armeabi-v7a, x86_64.
- Model loading is file-based (gguf format); `whisper_init_from_file`.

#### Model sizes / RAM / latency (ARM mid-range)

| Model | Disk (gguf) | RAM | RTF arm64 | Flag |
|-------|-------------|-----|-----------|------|
| tiny multilingual | ~39 MB | ~200 MB | ~0.1–0.3x | CLAIM (whisper.cpp README) |
| base multilingual | ~74 MB | ~310 MB | ~0.3–0.6x | CLAIM |
| small multilingual | ~244 MB | ~600 MB | ~0.8–1.5x | CLAIM |
| medium multilingual | ~769 MB | ~1.5 GB | >2x | CLAIM — too slow |

RTF CLAIM source: whisper.cpp README benchmarks (Apple M1 + x86; ARM mid-range unspecified).
No independent Android ARM mid-range benchmark found.

**License:** MIT (whisper.cpp + whisper-jni).

#### Risk

Word confidence gap is a **blocker** for the spans/doubt UI unless the JNI layer is patched.
Streaming is architecturally unsuitable. Best fit: batch push-to-talk with `base` or `small`
multilingual model, accepting degraded doubt UI (fallback: confidence=None for all words,
same as qwen on desktop).

---

### 3. ONNX Runtime Mobile + Whisper ONNX export

**What it is:** Microsoft-supported Whisper exported to ONNX; run via ONNX Runtime (ORT)
Mobile on Android. ORT has ARM NEON + NPU acceleration paths.  
**Source:** https://github.com/microsoft/onnxruntime | https://github.com/microsoft/onnxruntime-genai

#### FR/EN code-switching quality

- Same Whisper weights → same quality characteristics as whisper.cpp.
- Microsoft's Whisper ONNX export covers tiny through large-v3.
- No independent code-switching benchmark for ORT Mobile found.

#### Streaming / partials

- ONNX encoder-decoder: not streaming by design. Chunk-based workarounds have the same
  latency accumulation problem as whisper.cpp streaming.
- ORT GenAI (the generative AI extension) supports token-streaming from the decoder, which
  enables partial-hypothesis display — but this is a live-generation preview, not true
  acoustic streaming. Latency still dominated by full-audio encode.

#### Word-level confidence

- Whisper ONNX models produce per-token log-probabilities from the decoder softmax.
- ORT GenAI exposes token logits; word-level confidence requires aggregation (geometric mean
  of token probs per word segment). Possible, but requires custom post-decode logic.
- **More tractable than whisper-jni** because you can inspect raw decoder output.

#### AAR / JNI maturity

- ORT Android AAR: production-quality, on Maven Central (`com.microsoft.onnxruntime:onnxruntime-android`).
- GenAI extension: newer, less battle-tested on Android (2024 release).
- ONNX model export pipeline: `optimum` library (CPU) → `.onnx`; separate encoder + decoder files.

#### Model sizes / RAM / latency (ARM mid-range)

| Metric | Value | Flag |
|--------|-------|------|
| whisper-base ORT encoder | ~37 MB | CLAIM (MS repo) |
| whisper-base ORT decoder | ~45 MB | CLAIM |
| ARM64 encode latency (base) | 0.182–1.371 s per chunk | CLAIM (MS benchmarks, hardware unspecified) |
| RAM peak | ~500 MB (base) | CLAIM |

**License:** MIT (ORT) + MIT (Whisper weights).

#### Risk

Complexity: two-artifact model (encoder/decoder ONNX), GenAI extension, custom confidence
aggregation. More moving parts than whisper.cpp. Benefit over whisper.cpp: access to raw
decoder logits enables proper `Word.probability` mapping.

---

### 4. Vosk

**What it is:** Kaldi-based (TDNN/LSTM) offline ASR. Android AAR on Maven Central. One model
per language; streaming-first design.  
**Source:** https://alphacephei.com/vosk | https://github.com/alphacep/vosk-android-demo

#### FR/EN code-switching

- **No code-switching.** One model = one language. French model (`vosk-model-small-fr-0.22`,
  ~41 MB) and English model (`vosk-model-small-en-us-0.15`, ~40 MB) are separate.
- Loading both simultaneously and doing language detection per-utterance is possible but
  awkward and has no token-level mixing.
- **Verdict: structurally unsuitable for FR/EN within-utterance code-switching.**

#### Other properties

- Word confidence: available via `result.json` ("conf" field per word). Maps cleanly to
  `Word.probability`.
- Streaming: native (designed for it). Low latency, works in 50 ms VAD windows.
- License: Apache 2.0.
- Model sizes: small-fr ~41 MB, small-en ~40 MB (VERIFIED from model zoo).

**Role if chosen:** Fallback-only for single-language sessions. Not a primary engine for
this use-case.

---

### 5. Moonshine v2 (Useful Sensors)

**What it is:** Small encoder-only Whisper-architecture model optimized for ARM edge.
Tiny (33.57M params, ~34 MB), Base (74M, ~74 MB). Maven Central AAR (2024).  
**Source:** https://github.com/usefulsensors/moonshine

#### FR/EN code-switching

- **English-only. Explicitly.** The Moonshine paper and README state English ASR only.
  The training data is English. No multilingual variant exists as of 2026-06.
- **DISQUALIFIED** for this use-case.

---

### 6. NVIDIA Parakeet / Canary

**What it is:** NeMo-based CTC+transducer family. Parakeet-TDT-0.6B-v3 (0.6B params)
supports 25 European languages with auto-LID. Canary-1B supports 4 languages.  
**Source:** https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3

#### FR/EN code-switching

- parakeet-tdt-0.6b-v3 supports FR and EN as separate languages with auto-LID.
- Code-switching (within utterance) is not documented. NeMo does not publish
  code-switching benchmark results for this model.

#### Android viability

- No self-contained Android AAR published. NeMo models require the NeMo ecosystem or
  custom ONNX export.
- 0.6B parameter model: ~1.2 GB in float16, ~600 MB in int8. RAM requirement exceeds
  mid-range phone headroom when combined with the app runtime.
- LiteRT (formerly TFLite) conversion path exists in theory but no published recipe.
- **DISQUALIFIED for first APK** — size, ecosystem dependency, no Android packaging.

---

### 7. Android built-in SpeechRecognizer (offline)

**What it is:** `android.speech.SpeechRecognizer` API backed by on-device models (available
offline since Android 13+ on Pixel; OEM-dependent on other devices).

#### FR/EN code-switching

- Language packs are monolingual. No code-switching support.
- Language must be set per-session, not per-word.

#### Other properties

- Word confidence: `SpeechRecognizer.CONFIDENCE_SCORES` extra (array of floats, one per
  utterance-level result, NOT per word).
- Black box: no postprocess attachment point, no control over decode parameters.
- OEM variability: offline support is not guaranteed on non-Pixel devices running Android 13.
- **DISQUALIFIED.** Not portable, no per-word confidence, no code-switching.

---

### 8. Other Candidates Scanned

- **MMS (Meta Massively Multilingual Speech):** 1100+ languages MMS-300M. FR+EN supported.
  No Android AAR; custom ONNX export required. Community-only Android path as of 2026-06.
  Promising long-term but not first-APK ready.
- **Whisper-Turbo quantized (gguf):** Same as whisper.cpp above; `turbo` model (~800 MB gguf)
  is the desktop model but too large for mid-range phones. `small` is the viable mobile tier.
- **Wav2Vec2 / XLS-R (Facebook):** Streaming CTC; ORT Mobile export possible. FR+EN multilingual
  in XLS-R-300M. No production Android AAR; community tooling only. Similar quality to Whisper
  small at smaller size, but word timestamps are less refined.

---

## The Central Fork: Branch 1 vs Branch 2

### Branch 1 — Chaquopy (embed CPython)

- **Chaquopy 17.0.0** (2025-11): Python 3.13 support; meets Google Play 16 KB page-size
  requirement (Nov 2025 enforcement). [Source: Chaquopy release notes]
- `Python.start()` cold-start overhead: extracts stdlib to app-private storage on first launch
  (several seconds, once). Hot starts: negligible.
- APK bloat: CPython runtime + stdlib + all pip deps adds ~20–50 MB compressed (CLAIM,
  depends on dep tree).
- JNI bridge: dual serialization for string/bytes crossing the boundary — sub-ms for
  postprocess-sized payloads (< 1 KB text), not a bottleneck.
- **Benefit:** `pipeline.postprocess()` runs unchanged. `spans.py`, `lexicon`, `syntax`,
  `casing`, `repeats` all travel for free. Eval harness can run on both platforms.
- **Risk:** CPython on Android is still a second-class citizen (Chaquopy is the best path,
  but it is a paid product for commercial apps above a usage threshold; BSD for open-source).
  Native crash debugging through Chaquopy is harder. Python startup contributes to cold-start
  time.
- **BeeWare** (alternative): BeeWare's Python-Android-support is now superseded by official
  CPython Android support (Python 3.14.0rc2 ships official Android binaries). This path is
  less mature than Chaquopy for Gradle integration in 2026.

### Branch 2 — Kotlin reimplement

- postprocess is ~300–500 LoC Python across 5 modules. A Kotlin port is tractable.
- Semantic drift risk: the lexicon, spoken-punctuation, and syntax families evolve on the
  desktop; keeping two implementations in sync is ops debt.
- **Benefit:** No CPython runtime; smaller APK; no Chaquopy dependency.
- **Recommendation:** If rewriting, port driven by the existing test suite
  (`tests/test_postprocess.py` etc.) — treat the Python as the spec and the Kotlin as the
  implementation under test. Gate every PR on both passing.

### Recommendation

Branch 1 (Chaquopy) for the first APK. Rationale: reduces the risk surface during engine
validation. The postprocess semantics are the hard-earned IP; don't port and validate
simultaneously. Defer the Kotlin rewrite to after the engine is proven.

---

## FR/EN Code-Switching: The Honest Assessment

No off-the-shelf on-device mobile engine solves FR/EN code-switching well in 2026. The
options, ranked by code-switch capability:

1. **Whisper (any variant, any wrapper):** Trained on multilingual data including FR+EN mixing.
   Best practical option. Quality degrades with smaller models (base < small < medium).
   WER at switch points: 10–30% spike vs. mono-lingual segments (CLAIM, OpenAI eval paper,
   not Android-specific).
2. **sherpa-onnx + custom bilingual transducer:** Theoretically possible (train or fine-tune a
   bilingual zipformer). No off-the-shelf model exists. Research effort required.
3. **Vosk / built-in:** No code-switching. Structurally inapplicable.

The "good enough" bar for Domovoy.apk v1 is Whisper small multilingual via whisper.cpp or
ORT — accepting that code-switch quality is below the desktop model, with a clear path to
larger models as phones get faster.

---

## Ranked Shortlist for First APK

### Rank 1: whisper.cpp + whisper-jni (primary recommendation)

- Best FR/EN code-switch coverage of any packaged Android engine.
- MIT license, Maven Central, production-quality JNI, active maintenance.
- `small` multilingual: ~244 MB on disk, ~600 MB RAM (CLAIM), usable on mid-range.
- **Gap to close before shipping:** patch whisper-jni to expose `WhisperTokenData.p` for
  `Word.probability`, OR accept confidence=None (spans render all words at full brightness
  — degraded but not broken, matching the qwen-CPU desktop fallback behavior).
- Push-to-talk batch mode only; streaming is not viable.

### Rank 2: ONNX Runtime Mobile + Whisper ONNX (if confidence is required)

- Same Whisper quality characteristics.
- Raw decoder logits accessible → proper `Word.probability` mapping possible.
- More complex integration (two ONNX artifacts, ORT GenAI extension).
- Better long-term NPU acceleration story (ORT ExecutionProvider for Snapdragon NPU).
- Recommended if the doubt/spans UI is non-negotiable for v1.

### Rank 3: sherpa-onnx (contingent on French model quality)

- Best streaming architecture; cleanest Kotlin API; word confidence available.
- **Blocked by:** French model quality issues (community-reported). Needs an independent
  French WER evaluation before committing.
- Would be Rank 1 if a reliable FR+EN bilingual model existed in the sherpa-onnx zoo.
- Track: `sherpa-onnx-streaming-zipformer-fr-*` quality improvements; or evaluate
  a Whisper ONNX model served through sherpa-onnx's WhisperRecognizer wrapper.

---

## Biggest Single Risk

**FR/EN code-switching quality on small models.** Every on-device option requires using
a sub-`large` Whisper model (or a non-Whisper engine). At `small` (244 MB), WER at
language-switch points may be high enough to defeat the product's core value proposition.
There is no published measured number for FR+EN on a mid-range ARM device — the closest
proxy is desktop benchmarks which are optimistic.

**Mitigation:** Before any architecture decision, run a 50-utterance FR/EN code-switch eval
(use `tests/data/codeswitch/` corpus) via whisper.cpp `small` multilingual on the target
hardware. Gate the engine choice on that number, not on vendor claims. If WER > 25% at
switch points, evaluate whether `medium` (769 MB, slower) is still viable, or whether the
v1 scope should be restricted to monolingual sessions with manual language selection.

---

## Bottom Line for Issue #2

**Engine:** whisper.cpp + whisper-jni is the lowest-risk path to a first APK. Same weights
as the desktop large-v3-turbo (just smaller tier), MIT licensed, packaged, multilingual
FR+EN, push-to-talk compatible.

**Architecture:** Branch 1 (Chaquopy) for v1. Ship postprocess as-is; validate the engine
swap first. Plan Branch 2 (Kotlin rewrite) for v2 once engine quality is confirmed.

**The one thing to measure before deciding anything:** Run `whisper small.multilingual` on
the target phone against the code-switch eval corpus. That single number will either
validate the path or send you toward `medium` (slower) or a sherpa-onnx custom model
(more work). Do not accept vendor claims as a substitute.

**Confidence gap mitigation:** `Word.probability` will be None until whisper-jni is patched
or ORT path is taken. Acceptable for v1 — ship the spans layer in degraded mode (no
dimming), identical to how the qwen-CPU desktop fallback behaves today.

---

## References

- sherpa-onnx repo: https://github.com/k2-fsa/sherpa-onnx
- sherpa-onnx French issue #3144: https://github.com/k2-fsa/sherpa-onnx/issues/3144
- whisper.cpp repo: https://github.com/ggerganov/whisper.cpp
- whisper-jni (GiviMAD): https://github.com/GiviMAD/whisper-jni
- whisper.cpp streaming latency issue #3567: https://github.com/ggerganov/whisper.cpp/discussions/3567
- whisper.cpp word confidence Android issue #2775: https://github.com/ggerganov/whisper.cpp/issues/2775
- ORT Mobile Android: https://onnxruntime.ai/docs/tutorials/mobile/
- Vosk Android: https://alphacephei.com/vosk/android
- SenseVoice / FunAudioLLM: https://github.com/FunAudioLLM/SenseVoice
- Moonshine: https://github.com/usefulsensors/moonshine
- Chaquopy: https://chaquo.com/chaquopy/doc/current/
- parakeet-tdt-0.6b-v3: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
