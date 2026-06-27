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

| Vue complète (toggle dans le menu) | Le perchoir | Réglages |
|:---:|:---:|:---:|
| <img src=".github/bubble-full.png" alt="Full view: the whole take, word-wrapped, growing as you speak"/> | <img src=".github/tray-menu.png" alt="Tray menu: start/stop, copy last, history, settings, view toggle, about, quit"/> | <img src=".github/settings-langues.png" alt="Settings: searchable checklist of 100 languages, selected first"/> |

*(screens rendered from the actual widgets by `scripts/readme_screens.py` —
regenerate with `QT_QPA_PLATFORM=offscreen poetry run python scripts/readme_screens.py`)*

## Features

- **Live transcript** — while you speak, the bubble streams a ~1 Hz greedy
  preview of the last few seconds; on stop, the whole take gets a full
  beam decode. On a long take that final pass runs batched (VAD-chunked,
  parallel on GPU): a 3-minute monologue lands in about a second.
- **A bubble that tells you what's happening** — the waveform tracks your
  voice on a perceptual scale, so even quiet speech visibly moves the bars
  ("I hear you"); the bars are **green on GPU, blue on CPU**, so you always
  know which silicon is decoding (and a red flash for errors). That hue holds
  from first frame to last — while it decodes, a bright pulse sweeps across the
  bars ("I'm working"), and the take lands on a *brighter* flash of the **same**
  colour (so green only ever means GPU). By default the bubble shows your **whole take**,
  word-wrapped and growing as you speak (switch to the discreet one-line
  *minimal* pill in the tray or *Réglages*). The **tray glyph breathes** —
  calm at rest, livelier while recording, a travelling pulse while decoding, in
  the engine colour (toggle off in *Réglages*). Optional soft **start tick**
  (*Réglages*, off by default) confirms recording has begun. A slow decode
  (past ~3 s) shows a quiet **`(Ns)` counter** so it reads as *working*, not
  frozen; and if a final is ever lost after a preview was shown, the bubble
  **never recants** — it holds the salvaged words in **amber** with a `Ctrl+V`
  hint (it was copied) instead of red-flashing a failure. If the GPU drops to
  CPU mid-session, a one-time note says so (the bars go green→blue anyway).
  On multi-monitor,
  pick which screen the bubble uses in *Réglages* — pin it to a monitor
  (default: primary), follow the mouse, follow the active window (where your
  text lands; on Wayland, where the focused window isn't queryable, it falls
  back to the mouse's screen), or **mirror it on every screen** at once.
- **Code-switching first-class** — by default the model auto-detects among
  100 languages per take. In *Réglages* you can confine detection to your
  own set: one language forces it; several turns on **per-segment**
  detection, so the language is re-detected segment by segment and a
  mid-sentence switch from français to English survives intact ("can I
  switch to English" stays English, instead of becoming "peux-je changer en
  anglais"). No more random Cyrillic cameos when you mumble, either.
- **Fast delivery, X11 and Wayland** — short takes are typed into the focused
  window (X11 xdotool, modifier-safe); long ones are pasted (Ctrl+V, or
  Ctrl+Shift+V in terminals). On Wayland (GNOME) everything is pasted via
  ydotool (never typed — ydotool assumes a US keymap). The clipboard is
  always set as backup — and *Réglages* can **preserve and restore** it around
  a take (off by default), so a dictation doesn't clobber what you'd copied. It
  only ever restores genuine text: an image or file list on the clipboard is
  left untouched rather than destroyed by a text-only write-back.
- **Cleanup that knows its place** — spoken punctuation ("virgule",
  "point", "new line") in both languages, a personal lexicon for your
  jargon, and deterministic collapse of Whisper repetition loops. No AI
  rewriting: a visible mishear beats a confident wrong autocorrect.
- **Voice macros (quick-chat)** — a short spoken trigger expands to a canned
  text: say "lgtm" and get your full review sign-off, "standup billing" and get
  a filled template. Triggers fire only on an exact whole-take match (never
  inside a sentence), and the pack is a hand-editable JSON file you own. Pick a
  **role** in onboarding (eng / product / design / marketing / strategy) and a
  curated built-in pack activates instantly — your own macros always take
  precedence. Everything you've got shows in `tuparles cheatsheet`. *(Radial
  activation still coming.)*
- **History & stats, local forever** — every take lands in SQLite with
  its telemetry (duration, decode time, words/min, detected language).
  `tuparles history "query"` searches it; `tuparles stats` shows your
  dictation profile (débit, decode speed, language mix).
- **Analytics dashboard, all on your box** — a tray *Analytics…* window
  with three views: *Ton usage* (which voice commands and syntax features
  you actually use, and which you've never discovered), *Ta voix* (a tag
  cloud + keyphrases over your dictation history), and *Ton code* (the
  cached codebase analysis that seeds the decoder). Feature usage is
  tracked **locally and opt-out** — nothing leaves the machine; toggle it
  off or wipe it in *Réglages › Confidentialité*.
- **PII firewall — minimize before persist** — what you dictate is always
  pasted verbatim, but the *stored* copy is cleaned first: secrets and
  checksum-validated identifiers (IBAN, n° de sécu, credit card, API keys)
  are masked with a `<KIND>` placeholder before they ever reach
  `history.db`. High-precision detection only, so it destroys ~zero real
  text; on by default, a toggle in *Réglages › Confidentialité*. The
  analytics tag cloud also honours a frequency floor so a once-spoken name
  can be kept from surfacing. A *Pare-feu PII* editor adds your own terms
  in two tiers — **block** (masked, for confidential project/client names)
  and **alert** (surfaced, never auto-erased) — case- and accent-insensitive.
  A **dev-capture** toggle (off by default, *Réglages › Confidentialité*) can
  save each take's *raw, unredacted* audio locally for replaying a fix — and
  while it's on, the tray shows a **steady red dot** so it never records you
  silently (`TUPARLES_DEV` overrides the toggle either way).

## Architecture

```
            hotkey (Right Ctrl + Right Alt)
                          │
   mic ── 16 kHz mono ────┤
    │                     ▼
    │              ┌─────────────┐   final: batched beam   ┌─────────────────────┐
    ├─ levels ───► │   daemon    │ ──────────────────────► │ faster-whisper      │
    │              │  (Python)   │ ◄────────────────────── │ large-v3-turbo fp16 │
    ▼              └─────────────┘   partials: ~1 Hz greedy │ (GPU, persistent)   │
 waveform              │      │                            └─────────────────────┘
  bubble UI ◄──────────┘      ├─► punctuation → lexicon → repeat-collapse
  (live transcript)           ├─► type/paste into focus (X11 xdotool · Wayland ydotool) + clipboard
                              └─► history + telemetry + usage events (SQLite)
```

- **Primary engine**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  `large-v3-turbo` in float16, persistent on the GPU (~29x realtime
  measured on an RTX 4080). Finals go through the batched pipeline;
  partials are cheap greedy decodes of a sliding window.
- **CPU fallback**: [Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)
  via [antirez/qwen-asr](https://github.com/antirez/qwen-asr), a pure-C
  inference engine (OpenBLAS) — used automatically when no GPU answers.
- **CPU live partials**: qwen can't stream, so the preview text on a CPU
  session comes from a separate small whisper on CPU (`base` by default,
  greedy, bounded window) — faster-whisper's CT2 CPU backend, no CUDA. The
  qwen final decode still rules; partials just paint provisional text as you
  speak. Opt-out in *Réglages* (« Aperçu en direct sur CPU ») on a low-power
  box, where the bubble falls back to waveform-only.
- **Self-healing GPU**: if the CUDA context dies mid-session — a laptop
  suspend/resume is the classic culprit, leaving `nvidia-smi` happy but
  CUDA unusable — the engine rebuilds the context on the next take, and
  only drops to the CPU fallback if that also fails. A take never silently
  yields nothing.

## Install

One-liner (Linux — apt / pacman / dnf / zypper, X11; needs git + poetry.
Wayland adds one step, below):

```bash
curl -fsSL https://github.com/PLNech/TuParles/releases/latest/download/install.sh | bash
```

This pulls the repo, installs system + Python deps (mapping package names to
your distro), builds the CPU fallback engine, downloads the model weights, and
registers TuParles in your desktop's app launcher.

<details>
<summary>Manual setup</summary>

```bash
# system deps — pick your distro:
sudo apt install libopenblas-dev xdotool xsel libportaudio2 ffmpeg   # Debian/Ubuntu
sudo pacman -S --needed openblas xdotool xsel portaudio ffmpeg       # Arch
sudo dnf install openblas-devel xdotool xsel portaudio ffmpeg        # Fedora

git clone https://github.com/PLNech/TuParles && cd TuParles
poetry install
git clone --depth 1 https://github.com/antirez/qwen-asr vendor/qwen-asr
make -C vendor/qwen-asr blas
# model weights: see install.sh for the five files to fetch into models/
cp vocab.example.txt vocab.txt           # then add your own names/jargon
bash scripts/install_desktop.sh          # desktop launcher (optional)
poetry run tuparles
```

</details>

GPU (any recent NVIDIA card) is detected automatically and used for the
primary faster-whisper engine; without one, the C fallback engine
transcribes on CPU.

### Wayland

Same install, then this once — and log out and back in afterwards:

```bash
bash scripts/setup_wayland.sh   # input group · uinput rule · wl-clipboard/ydotool · daemon · GNOME extension
```

It adapts to your ydotool: Ubuntu's daemon-less 0.1.8 needs nothing more, while
modern ydotool (≥1.0, Arch/Fedora) gets a `ydotoold` **user service** + socket
env so delivery can inject keys. On GNOME it also installs a focus-window
extension for terminal paste detection (Ctrl+Shift+V); other compositors
(KDE, etc.) detect terminals by window title and otherwise fall back to Ctrl+V.

The daemon renders the bubble through **XWayland** on a Wayland session
(`QT_QPA_PLATFORM=xcb`, set automatically): native Wayland compositors ignore
a client's request to place itself, so the frameless bubble would otherwise be
centred and unable to pin to all desktops. The X11 path also works under
XWayland. If you force native Wayland (`QT_QPA_PLATFORM=wayland`), the daemon
still runs but the compositor controls the bubble's position and stickiness.

### Compatibility & troubleshooting

TuParles probes what your box can do at boot and logs a one-line capability
report (`tuparles diag` prints it any time). For the full picture — a per-setup
tool matrix, the X11/Wayland fallback chains, and fixes by symptom (nothing
pastes, accented-take freeze, queued take in the wrong window) — see
**[docs/CROSS_ENV.md](docs/CROSS_ENV.md)**. Hitting a bug? `tuparles report
"summary"` opens an issue pre-filled with your environment + capability line.

## Personal glossary

Copy `vocab.example.txt` to `vocab.txt` and put your recurring names and
jargon there — it biases decoding toward your vocabulary. The file stays
local (gitignored), like everything you dictate.

Better: let your own dictations grow it. `tuparles vocab suggest` mines
your history for recurring technical tokens and proper nouns;
`tuparles vocab review` walks you through them one by one (oui/non) and
appends the keepers. You approve every word — suggestions never auto-apply,
because a glossary that grows on its own is just autocorrect with extra
steps. Changes take effect on the next take, no restart.

## CLI

```bash
tuparles                  # start the daemon (or launch from your app launcher)
tuparles history          # last 20 takes
tuparles history "tokens" # search your dictations
tuparles stats            # local telemetry: takes, débit, decode speed, language mix
tuparles vocab suggest    # mine your history for glossary candidates
tuparles vocab review     # accept/reject them interactively
tuparles report "bug…"    # open a prefilled GitHub issue (no account data sent)
tuparles diag             # this box's capability report (paste into a bug report)
tuparles update           # check GitHub for a newer release (no token)
tuparles whatsnew         # the latest changelog section
tuparles cheatsheet       # every voice command & syntax phrase (searchable)
tuparles cheatsheet quote # …filtered (accent/case-insensitive)
                          # …or just dictate "que peux-tu faire ?" hands-free
tuparles onboarding       # « Comment tu parles ? » — personalize (text view)
tuparles onboarding --replay  # …re-run it even once configured
```

Everything lives in `~/.local/share/tuparles/history.db` and
`~/.config/tuparles/settings.json` — yours, on disk, never synced anywhere.
