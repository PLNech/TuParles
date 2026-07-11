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
  parallel on GPU): a 3-minute monologue lands in about a second. The live
  preview shows spoken punctuation, slashes and known mishears *as they'll
  land* ("slash impeccable" reads "/impeccable" while you speak), not the raw
  decoder words the final would then quietly fix.
- **Trims the silence for you** — if you leave the mic keyed after the last
  word, the dead lead/tail is trimmed off before decode, so a forgotten-mic
  take doesn't pay to decode empty seconds. The win is biggest without a GPU
  (the CPU engines decode every silent second — a 30 s tail can halve a qwen
  decode). Conservative by design: it only ever trims the ends, keeps a margin,
  and hands the engine the whole take at the least doubt. On by default; toggle
  in *Réglages* (*« Couper les silences en début/fin de prise »*).
- **A bubble that tells you what's happening** — the waveform tracks your
  voice on a perceptual scale, so even quiet speech visibly moves the bars
  ("I hear you"); the bars are **green on GPU, blue on CPU**, so you always
  know which silicon is decoding (and a red flash for errors). That hue holds
  from first frame to last — while it decodes, a bright pulse sweeps across the
  bars ("I'm working"), and the take lands on a *brighter* flash of the **same**
  colour (so green only ever means GPU). By default the bubble shows your **whole take**
  as a **ribbon** that grows *wide* along the bottom edge before it ever adds a
  line (up to 2 lines, ≈76 px): the freshest words stay bright and right-anchored,
  older text dims into a smaller history line above, and the beginning stays
  visible — the whole overview without a tower planted over your code. Tune
  « Largeur du bandeau » (0 = the discreet fixed pill), « Lignes du bandeau »
  and « Taille du texte » in *Réglages*, or switch to the one-line *minimal*
  pill. The **tray glyph breathes** —
  calm at rest, livelier while recording, a travelling pulse while decoding, in
  the engine colour (toggle off in *Réglages*). Optional soft **start tick**
  (*Réglages*, off by default) confirms recording has begun. A slow decode
  (past ~3 s) shows a quiet **`(Ns)` counter** so it reads as *working*, not
  frozen; and if a final is ever lost after a preview was shown, the bubble
  **never recants** — it holds the salvaged words in **amber** with a `Ctrl+V`
  hint (it was copied) instead of red-flashing a failure. If the GPU drops to
  CPU mid-session, a one-time note says so (the bars go green→blue anyway), and
  the **tray glyph stays a muted blue** the whole time you're on the CPU rung —
  even at rest — so a wedged GPU never hides behind a neutral idle icon.
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
- **Drive a REPL by voice** — say "slash" and get `/`, a path separator that
  glues like one: "slash compact" → `/compact`, "endpoint slash habits" →
  `endpoint/habits`, "code slash slash comment" → `code//comment`. A curated
  ontology of Claude Code commands fixes the spelling even when the decoder
  splits or accents the name ("slash pré tiret compact" → `/pre-compact`); extend
  it with your own via `slash_commands` in settings.
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
- **CPU fallback**: used automatically when no GPU answers. Two rungs, chosen
  by what's installed:
  - [whisper.cpp](https://github.com/ggml-org/whisper.cpp) via
    [pywhispercpp](https://github.com/abdeladim-s/pywhispercpp) — *preferred*
    when present (`poetry install --with whispercpp`). It takes an
    `initial_prompt`, so the personal glossary + carryover context bias the CPU
    decode exactly as they do on the GPU — the bias qwen structurally can't take.
    And ggml's runtime SIMD dispatch makes one source run on no-AVX2 x86 and ARM
    NEON, so the same rung serves a Pi-class home host
    (`docs/research/2026-06-28-stt-host-decision.md`). Model via *Réglages*
    (`whispercpp_model`, `base` default).
  - [Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) via
    [antirez/qwen-asr](https://github.com/antirez/qwen-asr), a pure-C engine
    (OpenBLAS) — the deeper fallback when whisper.cpp isn't installed.
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

## Mobile (experimental)

TuParles runs on Android too — the same privacy story, on the phone in your
pocket. The whole loop is local: **mic → native whisper.cpp → embedded CPython
`postprocess()` → text**, sharing *one* Python core with the desktop (no Kotlin
re-port, no dual-maintenance tax). No `INTERNET` permission is declared; the OS
itself denies any socket.

**👉 [Download the experimental APK](https://github.com/PLNech/TuParles/releases/tag/android-poc-0.1)**
(`android-poc-0.1`, ~212 MB — model bundled, installable today on arm64). It's a
proof of concept: a capture harness that records FR/EN code-switch prompts, runs
the desktop pipeline on-device, and lets you export takes to `dev@nech.pl` via a
local intent. Toggles for language (auto/fr/en) and postprocess (on/off). Build
and model-swap notes in [`android/README.md`](android/README.md).

### The plan

The embed path (CPython via Chaquopy + whisper.cpp via JNI) was chosen over a
Kotlin port after a research fan-out — see `docs/research/2026-06-27-android-*`.
It ships as a phased epic:

| Phase | Issue | Status |
|---|---|---|
| Portable core: split `config_core` | [#4](https://github.com/PLNech/TuParles/issues/4) | ✅ ([PR #9](https://github.com/PLNech/TuParles/pull/9)) |
| Externalise postprocess tables to JSON | [#5](https://github.com/PLNech/TuParles/issues/5) | ✅ ([PR #11](https://github.com/PLNech/TuParles/pull/11)) |
| On-device engine + packaging | [#3](https://github.com/PLNech/TuParles/issues/3), [#6](https://github.com/PLNech/TuParles/issues/6)–[#8](https://github.com/PLNech/TuParles/issues/8) | 🧪 POC shipped, productionisation open |

Epic: [#2](https://github.com/PLNech/TuParles/issues/2). The spike (commits
`e10ac02..f87d70b`) merged to `main` as `bc12fc4`; CI un-redding landed in
[PR #10](https://github.com/PLNech/TuParles/pull/10).

### Honest status

A POC, not a daily driver yet. The bundled `base` model is fast (~1.5 s/clip)
and keeps French as French, but fumbles some loanwords; `large-v3-turbo` is
flawless but ~30 s/clip on a mid-range phone (push it manually — see the Android
README). Two findings cost the most to learn: the native build **must** be `-O3`
(a debug `ggml` build is ~50× slower), and whisper's language **must** be `auto`
(a hardcoded `"en"` silently translated French to English). Tested on a
Fairphone 6; other devices unverified.

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
tuparles transcribe FILE… # batch-transcribe audio/video → FILE-transcript.{txt,json}
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

### Transcribe files

The same engine that powers push-to-talk also transcribes files offline — a
Zoom recording, a voice memo, anything ffmpeg can read (m4a, mp3, wav, even a
video's audio track):

```bash
tuparles transcribe meeting.m4a          # → meeting-transcript.txt (next to it)
tuparles transcribe a.m4a b.m4a          # several at once, one model load
tuparles transcribe --device cpu talk.wav   # force CPU (battery-friendly)
tuparles transcribe --model medium x.m4a     # heavier model for a kept transcript
tuparles transcribe --turn-gap 0 x.m4a       # disable turn seams (one block per segment)
tuparles transcribe --no-json x.m4a          # skip the JSON sidecar (txt only)
```

Each file becomes a sibling `<name>-transcript.txt` of `[mm:ss] text` lines,
so you can skim and jump to a moment. It uses the RTX 4080 when one answers and
falls back to a CPU model otherwise (never GPU-or-nothing), decodes batched with
VAD (a 30-minute recording in a couple of minutes on the GPU), and follows your
language selection so a code-switched meeting stays code-switched. The transcript
is **faithful**: known-mishear fixes from your lexicon, but no spoken-punctuation
rewriting or command parsing — a meeting is not a dictation. An existing
transcript is never overwritten without `--force`. Like everything else, the
audio never leaves your box.

**Turn seams.** Whisper often fuses several speakers' turns into one unbroken
paragraph, which reads (to a human or an LLM) as a single person's train of
thought — and once cost a real quote its true author. So a silence longer than
`--turn-gap` seconds (default 1.2, a conversational hand-off beat; intra-sentence
pauses rarely exceed ~1 s) splits the block and marks the new turn with a visible
`— ` at its own `[mm:ss]`. This is not diarization — no names, no speaker
identity — just a boundary you can see, so fused turns stop reading as one voice.
It's a setting (smart default on): `--turn-gap 0` turns it off, or set
`turn_gap_s` in your config.

**JSON sidecar.** Alongside the `.txt`, each file also gets a
`<name>-transcript.json` (schema v1) carrying what the human transcript throws
away: per-word probabilities, per-segment QC (`avg_logprob`, `no_speech_prob`,
`compression_ratio`), a computed `words_per_s` and a `low_confidence` flag, and
the turn-seam boundaries — at the **same block granularity** as the txt, so the
two files tell one story. It invents nothing (`null` where the decode was
silent) and reserves a `speakers` placeholder for future diarization. Handy for
`jq`, a QA pass, or any downstream tooling:

```json
{ "schema_version": 1, "source": "meeting.m4a", "duration_s": 1693.2,
  "model": "small", "device": "cpu", "language": "fr", "speakers": null,
  "messages": [ { "start": 0.0, "end": 12.3, "content": "…",
    "annotations": { "turn_seam": false, "avg_logprob": -0.31,
      "low_confidence": false, "words": [ { "w": "mot", "s": 0.0, "e": 0.4,
      "p": 0.97 } ] } } ] }
```

Default on; `--no-json` (or `transcribe_json: false` in your config) skips it.
