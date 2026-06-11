# Spike: STT backend selection (2026-06-11)

Hardware: i9-13900H (6P+8E, 20 threads), 64 GB RAM, CPU-only.
Test clip: 20 s real Fr-En code-switched speech, background jazz + vent noise,
tech vocab (deploy, KPI, CI, pull request). Recorded at desk — representative,
not flattering.

## Results

| Backend | 20 s clip | 4 s clip | Quality notes |
|---|---|---|---|
| qwen-asr 0.6B offline (antirez C, 14t) | 7.4 s (2.7x RT) | 4.2 s incl. spawn | Good. "pull request"→"boule request", "au feeling"→"au fil ligne" |
| qwen-asr 0.6B `--stream` (batch) | 22.5 s (0.89x RT) | — | KPI→API, CI→CIA |
| qwen-asr 0.6B `--stream` (real-time paced) | 45.8 s (0.44x RT) | — | Unusable: re-encodes partial tail repeatedly |
| faster-whisper small int8 | 5.0 s (4.0x RT) | ~5 s | "poule request", "CIA", "déploie" |
| faster-whisper large-v3-turbo int8 | 13.2 s (1.5x RT) | 12.5 s | **Best by far**: au feeling ✓, KPI ✓, CI ✓, pull request ✓ |

Beam size 1 vs 5: no meaningful speed or quality difference here.

## Key findings

1. **Whisper-family pays a fixed ~30 s encoder window per call** — a 4 s
   utterance costs the same as 25 s. `chunk_length` in faster-whisper does
   NOT reduce encoder compute (tested: no-op). This kills whisper for
   low-latency short dictations on CPU, despite turbo's superior accuracy.
2. **qwen-asr cost scales with audio length** (~2.6 s fixed + 0.24 s/s audio
   + 0.65 s process spawn; weights are mmap'd so spawn is cheap). Best
   latency profile for the interactive loop.
3. **qwen-asr interactive streaming is not viable on this CPU** — with
   real-time paced input it re-encodes the growing tail window and falls
   2.3x behind speech.
4. Prompt biasing (`--prompt`) is too soft to fix vocab mishears; a
   deterministic personal-lexicon post-processor will handle "boule request"
   → "pull request" instead.

## Decision

**MVP: qwen-asr 0.6B, segmented-offline pipeline.** Python daemon does VAD,
cuts speech at natural pauses into ~4-8 s segments, decodes each completed
segment offline (fast mode) while the speaker continues. Live partials appear
phrase-by-phrase in the bubble; on stop only the tail segment remains
(~3-4 s to final text). Personal lexicon layer fixes known mishears.

## v2 optimization tracks (not now)

- **whisper.cpp + `--audio-ctx`**: unlike CT2, ggml can actually shrink the
  encoder window proportionally to audio length. Could deliver turbo-class
  quality at qwen-class latency. Needs cmake.
- **OpenVINO**: encoder on the Iris Xe iGPU. Intel-specific, potentially 2-3x.
- **Background re-decode**: paste qwen text immediately, re-transcribe with
  turbo in the background for the searchable history archive (best of both).
