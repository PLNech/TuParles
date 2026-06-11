# TuParles

[![CI](https://github.com/PLNech/TuParles/actions/workflows/ci.yml/badge.svg)](https://github.com/PLNech/TuParles/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Local, private, push-to-talk dictation for people who code-switch entre le
français and English mid-sentence — and need their tech vocab (`max_tokens`,
KPIs, la contingence) to survive transcription.

Tap **Right Ctrl+Alt** → a small floating bubble appears with a live waveform
and the transcript streaming in as you speak → release (or tap again) → the
text is typed into whatever window has focus. Everything runs on-device.

<p align="center">
  <img src=".github/bubble-recording.png" alt="Recording: live waveform, transcript streaming in, freshest words kept visible"/>
</p>

| Vue complète (toggle dans le menu) | Le perchoir |
|:---:|:---:|
| <img src=".github/bubble-full.png" alt="Full view: the whole take, word-wrapped, growing as you speak"/> | <img src=".github/tray-menu.png" alt="Tray menu: start/stop, copy last, history, view toggle, about, quit"/> |

*(screens rendered from the actual widgets by `scripts/readme_screens.py` —
regenerate with `QT_QPA_PLATFORM=offscreen poetry run python scripts/readme_screens.py`)*

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

## Install

One-liner (Ubuntu/Debian, X11, needs git + poetry):

```bash
curl -fsSL https://github.com/PLNech/TuParles/releases/latest/download/install.sh | bash
```

This pulls the repo, installs system + Python deps, builds the CPU fallback
engine, downloads the model weights, and registers TuParles in GNOME search.

<details>
<summary>Manual setup</summary>

```bash
sudo apt install libopenblas-dev xdotool xsel libportaudio2 ffmpeg
git clone https://github.com/PLNech/TuParles && cd TuParles
poetry install
git clone --depth 1 https://github.com/antirez/qwen-asr vendor/qwen-asr
make -C vendor/qwen-asr blas
# model weights: see install.sh for the five files to fetch into models/
cp vocab.example.txt vocab.txt           # then add your own names/jargon
bash scripts/install_desktop.sh          # GNOME launcher (optional)
poetry run tuparles
```

</details>

GPU (any recent NVIDIA card) is detected automatically and used for the
primary faster-whisper engine; without one, the C fallback engine
transcribes on CPU.

## Personal glossary

Copy `vocab.example.txt` to `vocab.txt` and put your recurring names and
jargon there — it biases decoding toward your vocabulary. The file stays
local (gitignored), like everything you dictate: history lives in
`~/.local/share/tuparles/`, searchable via `tuparles history "query"`.
