# TuParles

Local, private, push-to-talk dictation for people who code-switch entre le
français and English mid-sentence — and need their tech vocab (`max_tokens`,
KPIs, la contingence) to survive transcription.

Tap **Right Ctrl+Alt** → a small floating bubble appears with a live waveform
and the transcript streaming in as you speak → release (or tap again) → the
text is typed into whatever window has focus. Everything runs on-device.

## Architecture

```
            hotkey (tap=toggle / hold=push-to-talk)
                          │
   mic ── 16 kHz mono ────┤
    │                     ▼
    │              ┌─────────────┐     raw s16le pipe     ┌──────────────────┐
    ├─ levels ───► │   daemon    │ ─────────────────────► │ qwen_asr --stream │
    │              │  (Python)   │ ◄───────────────────── │  (C, CPU/OpenBLAS)│
    ▼              └─────────────┘     partial tokens      └──────────────────┘
 waveform              │      │
  bubble UI ◄──────────┘      ├─► spoken-punctuation post-processor
  (live transcript)           ├─► xdotool type into focused window (+ clipboard)
                              └─► history (SQLite)
```

- **STT engine**: [Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)
  via [antirez/qwen-asr](https://github.com/antirez/qwen-asr), a pure-C CPU
  inference engine (OpenBLAS). Streaming mode decodes 2 s chunks with prefix
  rollback — that's what feeds the live transcript view.
- **Fallbacks**: whisper.cpp (plan B), faster-whisper (plan C), behind the same
  transcriber interface.

## Setup

```bash
sudo apt install libopenblas-dev xdotool   # one-time system deps
make -C vendor/qwen-asr blas               # build the C engine
poetry install
```

Model weights live in `models/` (gitignored), engine source in `vendor/`
(gitignored, cloned from upstream).

## Status

Early days — see task ledger. Spike phase: validating Qwen3-ASR-0.6B CPU
latency and Fr-En code-switching quality before committing to the backend.
