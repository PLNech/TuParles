# Audio preprocessing: trim the tail, don't touch the noise

*2026-07-11 — synthesis of a two-track investigation: SOTA survey (web) +
codebase audit. Seeds the preprocessing extension design.*

## The problem as reported

Users leave the mic keyed for seconds after they stop speaking; the silent
tail inflates decode time. Background music/noise separation was also floated
as a possible quality win.

## Finding 1 — the silent tail is real, but it's a *CPU-path* problem

The GPU path already skips silence: `GpuEngine.transcribe` decodes through
faster-whisper's `BatchedInferencePipeline` with `vad_filter=True`
(`engine.py:143-157`), which runs silero-vad over the full buffer and
feature-extracts only the speech chunks. The fallback rungs do not:

| Path | normalize_audio | VAD | Silent-tail cost |
|---|---|---|---|
| `GpuEngine` (final + partial) | yes | yes | mitigated internally |
| `WhisperCppEngine` | yes | **no flag passed** (`engine.py:422-426`) | full |
| `QwenCpuEngine` | **bypassed entirely** (`engine.py:306-348`) | none | full, pushes toward the hard 120s subprocess timeout |
| `filetranscribe.py` | **bypassed** | yes (`filetranscribe.py:235`) | mitigated |

So the feature that motivated this ("my decode takes too long when I forget
the mic on") pays off most exactly where the house doctrine cares most: the
CPU/train/battery story.

Two caveats that make pre-trim worthwhile even on GPU:

- faster-whisper's VAD defaults are conservative (`min_silence_duration_ms=2000`)
  — a 0.5-1.5s dead tail sails through. Our own
  `2026-07-08-cpu-asr-sota-and-decode-review.md` already proposed tuned
  `VadOptions` (500ms / `speech_pad_ms=200`); still unshipped.
- Whisper-family encoders cost ~constant per 30s window; trimming saves
  *window count*, a discrete win (45s take with a 20s tail: 2 windows → 1).
  Bonus: silence is the classic hallucination trigger ("Sous-titres par la
  communauté d'Amara.org") — trimming is also a correctness measure.

### Field forensics (2026-07-11) — the "GPU freeze" was the qwen rung

A perceived "GPU froze after a long take, partials flowed then a long wait
before paste" was checked against the journal + history DB (numeric columns
only). Every take from 07-09 to 07-11 12:49 ran on `QwenCpuEngine` (CUDA
presumably wedged post-suspend; a restart at 13:54 recovered `GpuEngine`).
The worst case: 51.2s audio → 20.8s decode + 0.8s lock + 1.9s deliver ≈ 23.5s
of dead air. Same day on healthy GPU: 34.8s audio → 1.0s decode. Partials
felt live because the small partials model kept up; the *final* full-buffer
qwen decode paid the whole price. This is the strongest real-world case for
trimming at capture handoff: the CPU rung decodes every silent second.

## Finding 2 — denoising before Whisper is evidence-against, not just unproven

The existing `preprocess.py` docstring ("we deliberately do NOT denoise")
survives contact with 2025-2026 literature, and then some:

- [arXiv:2512.17562](https://arxiv.org/abs/2512.17562): 500 recordings × 9
  noise conditions × 4 ASR models × MetricGAN+ enhancement — original noisy
  audio beat enhanced audio in **40/40 configurations**, even at mild SNR.
- [arXiv:2603.04710](https://arxiv.org/abs/2603.04710): SAM-Audio denoising
  before Whisper consistently raised WER despite better PSNR — and hurt
  *large* models more than small ones.
- Mechanism ([arXiv:2404.14860](https://arxiv.org/abs/2404.14860)):
  enhancement artifacts (musical noise, spectral holes) damage ASR more than
  the noise they remove. Whisper trained on 680k h of noisy web audio
  precisely so it wouldn't need a cleanup front-end.
- The only positive results use enhancement co-trained with the recognizer
  ([arXiv:2403.06387](https://arxiv.org/abs/2403.06387)) — not applicable to
  a frozen checkpoint.

demucs is the wrong tool class (music-stem separation, GPU-heavy);
DeepFilterNet is licence-clean (MIT/Apache-2.0, verified) but last released
Aug 2023; RNNoise (`pyrnnoise`) is the only candidate we'd ever consider,
strictly opt-in and eval-gated. **Default: no noise path.**

## Design — where the trim hooks in

**Hook at capture handoff, not per-engine.** Trim the buffer once where
`Recorder.stop()` returns it / where `_QueuedTake` is built
(`daemon.py:307-337`), so GPU, whisper.cpp, qwen, and any future engine get
it for free — which also fixes the qwen normalize-bypass as a side effect.
Invariant: never mutate `Recorder._chunks` (live capture) — trim only the
returned copy. Partials are safe: preprocess already runs per-decode-call on
tail-window snapshots (`daemon.py:269`), non-destructively.

**Trim mechanism, GPU-or-CPU by construction:**

- Primary: **silero-vad batch API** (`get_speech_timestamps`), ONNX CPU
  runtime, MIT, ~0.6% RTF (165× realtime on one core) — same cheap path on
  both legs, no CUDA anywhere in the step.
- Fallback (silero unavailable/broken): deterministic RMS tail-trim
  (librosa-style `top_db`, self-implemented to avoid the dep). Trailing
  silence after speech is the *easy* one-sided case; energy thresholding is
  honest work there.
- Padding: keep **~200ms pre-roll / 300-500ms post-roll** margins around
  detected speech (silero's 30ms default pad is tuned for telephony, not
  ASR). Cap interior pauses rather than deleting all pause structure.
- "It's a setting": `trim_silence` on by default, Réglages toggle
  (`Couper les silences en début/fin de prise`), pad margins as tunables.

**Complement:** pass tuned `VadOptions` to the faster-whisper call sites
(the D-series item from 2026-07-08) — pre-trim and in-decode VAD are
complementary, not redundant.

## Validation gate (before the default flips on)

- **Real takes**: `scripts/replay_takes.py` A/B (trim on/off) over stored
  take WAVs — WER drift per take + `decode_s` delta. Respect the
  review_takes consent gate.
- **Codeswitch corpus**: `tests/data/codeswitch/` slot-check gate must stay
  green; WER via paired comparison, **report a bootstrap 95% CI on ΔWER**,
  not a bare point estimate — at n≈dozens only large effects are detectable,
  and we say so.
- **Structural clip check**: duration-delta + false-clip rate (trimmed span
  vs expected speech span) as a WER-independent safety metric.
- **Success metric already instrumented**: `decode_x_realtime` in
  `history.summarize()` (`history.py:177-180`) and the per-take journal line
  (`audio_s` vs `decode_s`, `daemon.py:428-434`) — before/after is measurable
  with zero new plumbing.

## Ruled out (and why)

- webrtcvad: dead upstream; ~50% TPR vs silero's ~88% at 5% FPR.
- pyannote segmentation: offline diarization tool, wrong weight class.
- TEN VAD: plausible marginal RTF win, unproven; not worth a second VAD dep.
- demucs / MP-SENet / diffusion SE: wrong tool or research-stage.
- Generic denoising by default: actively harmful per 40/40 sweep above.
