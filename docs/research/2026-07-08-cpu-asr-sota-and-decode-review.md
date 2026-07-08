# CPU ASR, state of the art — a fan-out review of our own decode path

*2026-07-08. Trigger: the GPU wedge is worse than modeled — after suspend/resume,
CUDA reports available, the model loads, and decode fails anyway; only a reboot
truly clears it. So the CPU path is not a fallback, it is the primary path an
unknown fraction of the time — and it is the whole path on Android. Four
parallel reviews ran: three web sweeps (Whisper-CPU ecosystem / new ASR actors /
mobile-edge inference) and one fresh-eyes source-level review of
`filetranscribe.py` + `engine.py` against the installed faster-whisper 1.2.1 /
CTranslate2 4.8.0. This note is the synthesis; links in `SOURCES.md`.*

## 0. The one-line verdicts

- **Our whisper.cpp N-rung plan (2026-06-28 gradient note) survives contact
  with the 2026 landscape** — nothing found dethrones it for the portable rung.
- **The faster-whisper file path we shipped yesterday has real headroom**: the
  batched pipeline silently disables Whisper's robustness machinery, we import
  torch for one boolean, and the decode-time wedge is unguarded (fixed same-day).
- **Nobody — not NVIDIA, not Mistral, not Kyutai, not Alibaba — publishes an
  FR/EN code-switch number.** Our eval corpus is a differentiator, not a
  catch-up item. Every candidate below gets judged by
  `tests/data/codeswitch/` or not at all.

## 1. The 2026 landscape beyond Whisper (who could replace `small`)

| Candidate | Size | FR | License | CPU story | Timestamps | Catch |
|---|---|---|---|---|---|---|
| **Parakeet TDT 0.6B v3** (NVIDIA, 2025-08) | 600M | yes (25 langs) | CC-BY-4.0 | `parakeet.cpp` (ggml, MIT, v0.4.0 2026-07-01): ~1.4× NeMo, claims far past whisper.cpp on CPU | word/seg/char | zero code-switch validation; sources explicitly call Whisper "the safer default for heavy code-switching" |
| **Qwen3-ASR-0.6B** (Alibaba, 2026-01) | 0.6B | yes (52 langs) | Apache 2.0 | faster-than-RT on a 4-core Xeon; `CrispASR` pure-C++ GGUF | separate ForcedAligner pass | timestamps cost a 2nd model |
| **Kyutai stt-1b-en_fr** | 1B | **natively bilingual EN+FR** | CC-BY-4.0 | unverified on x86 (MLX port exists) | word-level built in | no CPU RTF published — needs our own bench |
| **Voxtral Mini/Realtime 4B** (Mistral, 2025-07→2026-02) | 3-4B | strong | Apache 2.0 | community C ports (antirez `voxtral.c`); vendor targets GPU | word-level (13 langs) | an order of magnitude too heavy for "laptop on the train" |
| **SenseVoiceSmall** (Alibaba) | ~234M | *(desktop claim conflicts: one sweep says 50+ langs, the mobile sweep confirms **no French**)* | verify | llama.cpp/GGUF single binary since 2026-06 | unclear | resolve the FR contradiction before spending a minute more |
| **Moonshine v2** (2026-02) | 26-245M | **no official FR** (community tiny-fr: 21.8% WER MLS-FR, ~9× RT CPU) | MIT | best edge latency surveyed | word-level | one-model-per-language doctrine = structurally anti-code-switch |
| Granite Speech 4.1 2B (IBM, 2026-04) | 2B | yes (6 langs) | Apache 2.0 | no CPU bench found | word + speaker-attributed | unproven on CPU |

**Reading**: two spike-worthy drop-ins — **parakeet.cpp** (speed king) and
**Qwen3-ASR-0.6B** (license + language breadth) — plus **Kyutai** as the
philosophical wildcard (a French lab shipping a single bilingual FR+EN
checkpoint is the closest thing to our exact problem). All three enter through
the same gate: the code-switch eval, WER + RTF, CPU-only, before any ladder
placement. Moonshine-tiny-fr is a rung *below* `base` for desperate hardware,
not a `small` replacement.

## 2. Whisper-stack findings (the path we actually ship)

- **Batched ≠ sequential + faster.** Verified in faster-whisper 1.2.1 source:
  `BatchedInferencePipeline` does **no temperature fallback** (single
  `sampling_temperature=temperatures[0]` call), hard-forces
  `condition_on_previous_text=False`, `hallucination_silence_threshold=None`.
  We pay beam_size=5 (~5× greedy) while the cheaper rescue machinery is off.
  For offline meetings the sequential path with the full robustness stack may
  win outright — bench it (D1 below). One real batched advantage to measure
  before discarding: it re-applies `initial_prompt` (the glossary) per chunk;
  sequential seeds only window 1.
- **Silero VAD v6.x** (v6.0 2025-08, v6.2 late 2025): 11-16% fewer VAD errors
  vs v5, redesigned for edge cases. Check which version faster-whisper 1.2.1
  vendors; if v5-era, an upgrade is a free win.
- **VAD defaults are tuned for clean audio, not meetings**:
  `min_silence_duration_ms=2000` + `max_speech_duration_s=inf` means crosstalk
  can grow a segment until a 2 s silence that never comes, then a blunt 30 s
  split smears the timestamps we sell. Candidate:
  `min_silence_duration_ms=500, max_speech_duration_s=30, speech_pad_ms=200`.
- **Language hints are a code-switch hazard**: a *wrong* forced language token
  costs up to ~19% relative WER on French code-switch conditions. Our
  per-segment auto policy (`decode_language_opts` → `multilingual=True`) is the
  right doctrine; audit that no path hardcodes a hint.
- **beam_size=1 vs 5 on CPU**: literature suggests <1.5pp WER for a large
  latency win. For the *file* path quality wins; for realtime CPU partials we
  already run greedy. A/B anyway — it prices the beam.
- **cpu_threads**: CT2 default grabs all logical cores; E-cores oversubscribe
  BLAS-bound decode. We already measured the P-core plateau for qwen
  (`config.py` QWEN_THREADS=14); thread it into the CT2 paths as a smart
  default + setting.
- **int8 vs int8_float32**: float32 accumulation is CT2-CPU-valid and typically
  near-free on VNNI; measurably safer on multilingual. Bench cell, not a guess.
- **Quantization granularity** (arXiv 2511.08093, exactly whisper-`small`
  int8): per-channel scaling + calibration-set choice matter more than int8
  flavor. Long-shot lever: re-quantize with our FR/EN corpus as calibration.
- **`large-v3-turbo` int8 as the CPU *file* model**: unifies the model family
  GPU↔CPU, and the gradient note already pencils ~1× RTF on the i9. Offline can
  spend that. distil-large-v3(.5) is English-only — wrong tool here; the only
  French distils are bofenghuang's 2024 vintage, unrefreshed.

## 3. Mobile/edge findings (the Android trajectory)

- **CPU/NEON whisper.cpp remains the honest floor.** Vulkan-on-Android is an
  *open issue* (#2370), not a matured path — the 2026 maturity story is
  desktop-only. Every NPU number published (Qualcomm AI Hub whisper-small
  w8a16: encoder ~174-224 ms per 30 s window ≈ >130× RT on 8-Elite Hexagon) is
  flagship silicon; nothing targets the Fairphone 6's Snapdragon 7s Gen 3.
  Budget CPU-only as the real ceiling until measured otherwise.
- **The 2026 consolidation story is Google LiteRT unifying NPU vendors**
  (Qualcomm + Tensor + MediaTek in one delegate stack; Argmax Pro SDK 2026-03
  builds on it, serving Whisper *and* Parakeet). WhisperKitAndroid was archived
  2026-01 in favour of it — a one-year shelf life for a bespoke runtime. Watch,
  don't adopt; re-evaluate in 2-3 quarters.
- **ExecuTorch is the spike candidate**: official maintained Whisper + Parakeet
  Android examples (PyTorch blog 2026-03-16), XNNPACK/Vulkan/QNN backend
  matrix, LM Studio ships it in production (desktop). No published mobile RTF —
  which is exactly what a Fairphone 6 spike would produce.
- **Play "on-device AI" delivery (beta)** is the first-party answer to our
  212 MB APK: install-time / fast-follow / conditional-per-device model
  delivery. Replaces hand-rolled download-on-first-run if Play distribution
  lands in scope.
- **Android 15/16 FGS rules**: mic foreground service cannot start from
  background; push-to-talk fits, always-listening doesn't. ~5-7% battery per
  30 min transcription on mid-range silicon (2026 app comparisons); nobody
  published a 28-min thermal case study — measure on the FF6.
- sherpa-onnx: fast flagship (SenseVoice) has no French; the FR streaming
  zipformer is 2023-era and reported weak on a 4 GB phone (issue #3144, 2026-02).
  Also its Whisper ONNX exports showed accuracy drift vs faster-whisper
  (issue #2900) — ONNX export is not automatically accuracy-neutral.

## 4. Fresh-eyes review of our own path (faster-whisper 1.2.1 verified)

Shipped same-day as quick wins:
- **F3 — decode-time wedge guard**: `FileTranscriber.transcribe()` drained a
  lazy generator with no try/except; a post-resume wedge (load succeeds, decode
  throws) sank whole files. Now mirrors ResilientEngine: catch → warn → reload
  CPU → restart decode.
- **F4 — torch import dropped**: `pick_device` imported ~2 GB of torch for one
  boolean; now probes `ctranslate2.get_cuda_device_count()` (what actually
  decodes; the eval harness already did it right). Lean-install and mobile both
  care. Bonus: ct2's probe may also disagree less with a wedged driver than
  torch's cached answer — observe in the wild.

Bench-gated (extend `bench_cpu_stt.py`, don't rebuild; WER **and** RTF per
cell, print n + bootstrap CI — the corpus is small and synthetic, so relative
ranking only, real-human capture queued before locking a tier):
- **D1** batched (bs 4/8/16) vs sequential+temp-fallback+hallucination-silence
  — the F1 decision.
- **D2** model × quant: {small, turbo, medium} × {int8, int8_float32}; does
  turbo int8 clear ~1.5× RTF on the i9? On the Pi 5?
- **D3** cpu_threads {6, 14, all}: does the qwen P-core plateau hold for CT2?
- **D4** glossary adherence: batched per-chunk prompt vs sequential window-1
  (add a vocab-recall metric).
- **D5** the still-owed `#4` bar: whisper.cpp-q5 vs qwen with prompt-bias, Pi
  A76 (from `2026-06-28-stt-host-decision.md`).
- **D6** (new, from the landscape): parakeet.cpp + Qwen3-ASR-0.6B + Kyutai
  stt-1b-en_fr through the same harness — entry exam for the ladder.
- **D7** (user-greenlit direction): two-pass "fast transcript with
  error-recovery" — greedy/cheap first pass, then targeted re-decode of
  low-confidence spans only (the #23 word-confidence machinery already marks
  doubt spans) with a stronger model/beam. CPU-native thinking: spend the
  expensive decode only where the cheap one wavered. Compare against D1's
  sequential-with-temp-fallback — they are cousins (Whisper's fallback re-runs
  whole segments; D7 re-runs only doubted spans, possibly with a *different*
  model).

Design-sized, deliberately not decided today:
- **F7 — three CPU decoders is one too many.** The file path proved CT2-on-CPU
  is promptable + per-segment multilingual + word-confidence — everything qwen
  lacks and whisper.cpp was adopted to restore. Honest split candidate:
  CT2 for AVX2 desktops (realtime final included), whisper.cpp scoped to
  musl/ARM/no-AVX2 portability, qwen retired if D-series numbers agree.
- **F1/F2** land or die by D1/D2.
- VAD meeting-tune + `int8_float32` + cpu_threads-as-setting ride the same
  bench sprint.

## 5. What we did NOT find

- No FR/EN code-switch benchmark anywhere in industry or academia (CS-FLEURS
  arXiv 2509.14161 covers 113 pairs — check if FR-EN is among them; KIT's 2026
  papers retrofit CS robustness via adapters, a template if off-the-shelf
  disappoints). The moat holds; keep investing in the corpus.
- No rigorous RTF number for any Whisper-class model on any named mid-range
  phone SoC. Our own Fairphone 6 measurements are worth more than the entire
  survey — publish them (#42 blog seed).
- No 2025/2026 refresh of French-specific Whisper distillation. If we ever
  want one, we make it (BaldWhisper arXiv 2510.08599 is the recipe, built for
  code-switch robustness).

*Quatre éclaireurs, une carte. The scouts agree: the road we picked is still
the road — but we'd been driving it with the seatbelt unbuckled.*
