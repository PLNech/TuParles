# Speaker Diarization for a Local faster-whisper Pipeline (2025-2026)

*Researched 2026-06-23. Verbatim research brief.*

**Bottom line up front:** Add **WhisperX** to the existing faster-whisper setup. It bundles forced word-alignment (French + English both first-class) plus **pyannote.audio 4.x** diarization, and does the word→speaker assignment for you. One library, one `pip install`, runs comfortably on the 4080.

## Comparison table

| Option | Mode | Bundles ASR+align? | Speaker count | Realistic meeting DER | FR support | VRAM (4080) | License | Maturity |
|---|---|---|---|---|---|---|---|---|
| **WhisperX** (m-bain) | Offline | **Yes** (faster-whisper + wav2vec2 align + pyannote diarize + assign) | Auto / min/max | Inherits pyannote (~17-22% AMI) | **Yes** (wav2vec2 FR + EN bundled) | <8 GB | BSD-2 (code); models CC-BY-4.0 | Active, v3.8.6 (May 2026) |
| **pyannote.audio 4.x** (`community-1`) | Offline | No (diarization only) | Auto / num / min-max; no hard cap | AMI-IHM 17.0, AMI-SDM 19.9, DIHARD3 20.2, VoxConverse 11.2 | Inferred (acoustic, REPERE-FR in train set) | 6-8 GB | MIT code; **CC-BY-4.0** model | Mature, 4.0.5 (Jun 2026) |
| **pyannote 3.1** (legacy) | Offline | No | Same | AMI-IHM 18.8, DIHARD3 21.4, VoxConverse 11.2 | Inferred | 6-8 GB | **MIT** model | Mature, superseded |
| **whisper-diarization** (MahmoudAshraf97) | Offline | **Yes** (Demucs + faster-whisper + NeMo MSDD + forced align + punct realign) | Auto (NeMo clustering) | Higher accuracy on overlap (heavier stack) | Via faster-whisper/NeMo | Higher (Demucs+NeMo) | BSD-2 | Active (Feb 2026) |
| **NeMo Sortformer** (`diar_sortformer_4spk-v1`) | Offline | No | **Hard cap 4** | DIHARD3 14.76, CALLHOME-2spk 5.85 | **English-primary; FR degrades** | A6000-tested | **CC-BY-NC** (non-commercial) | New, SOTA-ish ≤4 spk |
| **NeMo Streaming Sortformer** | **Online** | No | **Hard cap 4** | DIHARD3 ≤4spk 15.09 @1s latency | English-primary | Memory-bounded | Verify per-card | New (Aug 2025) |
| **diart** (juanmc2005) | **Online** | No | Incremental discovery, no count needed | Online DER penalty vs offline | Inherits pyannote | Tens of MB | MIT (code) | Active, v0.9.2 (Feb 2026) |
| **DiariZen** (BUT) | Offline | No | max-cap | **Best in class**: AMI-SDM 13.9, DIHARD3 14.5, VoxConverse 9.1 | Inherits | WavLM-based | **CC-BY-NC** (non-commercial) | New (2026), research |
| faster-whisper native | — | — | **None** | — | — | — | — | — |
| whisper.cpp `-tdrz` | — | Turn-change only | Detects *changes*, not identities | **English only** | tiny | MIT | Experimental |

## Answers to specific questions

**1. Offline vs online maturity.** Offline/batch is mature and is what you want for post-meeting transcripts — pyannote 4.x and WhisperX are production-grade. Online/streaming (diart, Streaming Sortformer) is newer; trades DER for latency. For meeting transcripts, go offline.

**2. Speaker count.** No need to know it in advance with pyannote/WhisperX/diart — all auto-detect (you *may* pass `num_speakers` or `min/max_speakers`). Big exception: **NeMo Sortformer is hard-capped at 4 speakers** and degrades sharply at 5+.

**3. Realistic DER on messy meetings.** Expect roughly **17-22% DER** with pyannote `community-1` (AMI-IHM 17.0%, AMI-SDM 19.9%, DIHARD3 20.2%). Overlap is the dominant error source — WhisperX's README states plainly *"overlapping speech is not handled particularly well… diarization is far from perfect."* DiariZen pushes meeting DER to ~14% but weights are **non-commercial**. **French:** diarization is acoustic not lexical, so FR works in practice (pyannote trained on French REPERE), but FR support is *inferred*, not guaranteed. NeMo is English-primary — avoid for FR.

**4. Standard integration pattern.** transcribe → word timestamps → diarize separately → assign each word to the speaker whose turn overlaps it most. **WhisperX does this cleanly** via `assign_word_speakers()` (interval-tree overlap, `fill_nearest=True`). `whisper-diarization` does it with a heavier, higher-accuracy stack. Raw pyannote/NeMo means writing the overlap mapper yourself.

**5. GPU + latency on the 4080.** Comfortable. WhisperX large-v2 <8 GB at beam_size=5; turbo smaller; diarization adds modest VRAM. pyannote ~6-8 GB, well under realtime. 16 GB is ~2× the headroom needed.

**6. Licensing gotchas.**
- **pyannote needs an HF read token AND you must click "Accept" on each gated model card** — `speaker-diarization-community-1` *and* `segmentation-3.0`. Miss one and the pipeline silently fails to load. Applies via WhisperX too.
- Licenses: `segmentation-3.0` + `speaker-diarization-3.1` are **MIT**; `community-1` is **CC-BY-4.0** (commercial OK). WhisperX code BSD-2.
- **Non-commercial traps:** NeMo Sortformer v1 and DiariZen weights are **CC-BY-NC**.

## Recommendation: fastest path to who-said-what

1. `pip install whisperx` (pin **v3.8.6**; avoid yanked 3.8.2/3.8.3/3.7.3).
2. HF token; accept conditions on `pyannote/speaker-diarization-community-1` and `pyannote/segmentation-3.0`.
3. Pipeline: `transcribe (large-v3-turbo, fp16)` → `load_align_model(fr/en)` + `align()` → `DiarizationPipeline(token=...)` → `assign_word_speakers()`.

If higher overlap accuracy needed later, `whisper-diarization` is the upgrade.

## Caveats

- **Torch pin collision (most likely friction):** WhisperX v3.8.6 hard-pins `torch ~=2.8.0` / `torchaudio ~=2.8.0` and `pyannote-audio >=4.0.0`. Can force a torch upgrade in our CUDA/fp16 env — test in a throwaway venv first, or call WhisperX align/diarize standalone against our current faster-whisper to keep our torch.
- **Overlapping speech and turn boundaries** are where accuracy bleeds (~89 ms boundary error). pyannote `community-1` has an **exclusive diarization mode** (one speaker per instant) that makes word-alignment cleaner.
- **Don't pick NeMo** unless ≤4 speakers, English-only, streaming.
- **For our dual-channel capture (mic vs monitor), channel identity is free ground-truth "me vs them" diarization — diarization models only matter for splitting multiple remote speakers on the single monitor channel.**
