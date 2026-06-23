# Changelog

## Sprint 3 — 2026-06-23 · Cap sur les réunions, et Wayland sans X11

### Added
- **Microphone selection** in *Réglages* — pick your input device instead of
  PortAudio's default ("the first mic isn't always the right one"). Stored by
  name (indices shuffle on Bluetooth/USB hotplug, names don't), re-resolved per
  take, falls back to the default if it vanished mid-session (#40)
- **Native Wayland (GNOME) support** (#1): evdev hotkey backend (reads
  `/dev/input` — Wayland never forwards global keys to clients; needs the
  `input` group), ydotool + wl-copy delivery (never types — ydotool assumes
  a US keymap and garbles azerty). Per-device modifier tracking: Ctrl on one
  keyboard never combines with Alt on another into a phantom combo; live device
  hotplug rescan.
- **GNOME focus-window extension** (`packaging/gnome-extension/`, #1): publishes
  the focused window's class on the session bus — the only way a Wayland client
  can read it — so paste picks Ctrl+Shift+V in terminals, Ctrl+V in apps.
  Graceful Ctrl+V fallback when absent. `scripts/setup_wayland.sh` does the
  one-time privileged setup (input group, uinput rule, wl-clipboard/ydotool,
  extension install), idempotent, refuses sudo.
- **Meeting note-taking research**: six verbatim SOTA briefs in
  `docs/research/` — commercial landscape (Granola/Otter/…), a close-range
  Granola deep-dive, speaker diarization (WhisperX + pyannote), local LLM
  summarization (Ollama, augment-my-notes), Linux dual-side capture (mic +
  monitor = free diarization), voice command-and-control (Dragon/Talon) — plus
  `SOURCES`. Opens the Sprint 3 backlog (#35-#42)

### Changed
- `delivery`/`hotkey` choose their backend from one `IS_WAYLAND` probe so they
  can't disagree. **X11 path unchanged** (byte-equivalent). `_TERMINALS` now
  also matches `gnome-terminal`/`org.gnome.console` (incidentally fixes X11
  detection) (#1)
- **README** told the truth again: code-switching is per-segment detection,
  not the removed detect-then-snap; documented the self-healing GPU

### Fixed
- **Wayland auto-paste landed nowhere** (#1). Root cause, proven after three
  wrong guesses (ydotool syntax, paste combo, device delay): the Qt bubble
  STEALS keyboard focus on Wayland — Mutter ignores the no-focus hints X11
  honours — so the ydotool paste fired into the bubble, not the user's window
  (measured 0/8 with the bubble up → 8/8 hidden). Fix: capture the focus class
  at take-START, and hide the bubble on the GUI thread right before the
  keystroke so focus returns to the target.
- **Self-healing CUDA**: a laptop suspend/resume invalidates the long-lived
  CUDA context — `nvidia-smi` stays happy but context creation throws
  `unknown error`, and the old design only fell back to CPU at *load* time, so
  every post-resume take silently yielded nothing. The engine now rebuilds the
  context on a decode failure (fresh context in-process) and only drops to
  qwen-CPU if that also fails (`ResilientEngine`)
- **CI was red** for four runs: the suite grew numpy-importing tests but CI
  installed only pytest+ruff → collection error. Now installs numpy

### Infra
- **CI is a cross-OS matrix**: ubuntu/macos/windows × py3.11/3.12 — proves the
  pure-python layer is portable. CUDA and the Qt/audio frontends can't run on
  hosted runners (no GPU, no display); they're validated locally

### Doctrine
- **Store hardware identities by stable name, not enumeration index** — indices
  shuffle on hotplug, names survive.
- **A long-lived GPU context is fragile across power events.** Resilience is
  rebuild-then-fallback, not load-time fallback alone. Forensic tell: a journal
  suspend/resume pair + a GUI stall at the resume timestamp names the cause.
- **Forensics before theory, again**: an evdev monitor and a focused-QLineEdit
  harness disproved the ydotool-syntax and device-delay theories and pinned the
  focus-theft. The memory note that *named* the wrong cause was corrected, not
  trusted.

## Sprint 2 — 2026-06-23 · Le grand débogage: code-switching réel, gel terrassé, voix sous contrôle

### Added
- Notification-area tray: Dicter, Copier la dernière, Historique submenu,
  Réglages…, Affichage complet toggle, À propos, Redémarrer, Quitter (#12)
- Settings dialog: searchable checklist of Whisper's 100 languages,
  selected-first, hot-reloaded per decode (#20)
- Local telemetry + `tuparles stats`: per-take audio/decode/deliver times,
  WPM, chars, detected language; schema migrates old DBs in place (#27)
- Vocab tooling — `tuparles vocab suggest|review|add`: mines your own
  history for tech tokens + proper nouns, suggestions-only, hot-reloaded (#22)
- Hold-to-talk: hold the combo past 0.5 s = PTT (release stops), tap still
  toggles; a hold never kills a take it didn't start (#23)
- Audio normalization before STT: peak-normalize + DC-offset removal so
  quiet takes decode better (no-op on loud audio, never clips)
- **Esc cancels an in-flight take**: discard audio, no decode/delivery;
  Ctrl+C intentionally left ungrabbed
- View toggle: minimal pill ↔ full wrapped text (#14)
- README refresh (GPU-first architecture, features, settings screenshot, CLI)

### Changed
- **Code-switching is real now**: multi-language selection →
  `multilingual=True` (per-segment language detection). Was forcing one
  language for the whole take, frenchifying the other ("can I switch to
  English" → "peux-je changer en anglais"). 1 selected = forced, 0 = auto,
  2+ = code-switch. Removed the detect-then-snap path (#20)
- Final decode runs through `BatchedInferencePipeline` (VAD-chunked,
  parallel) — long takes land in ~1 s instead of freezing for a minute (#26)
- Delivery: paste is unconditional for paste-destined text (long OR
  non-ASCII), never re-typed; clipboard is the guarantee
- Bubble follows the cursor's screen, sticky across all virtual desktops (#25)

### Fixed
- **The freeze saga** (#26, #29): paint-loop trim was O(n)·30fps →
  memoized bisect; partials capped at 800 chars; glossary prompt echo in
  the live preview dropped (#28); **paste-then-type-during-freeze** — a
  paste-destined text whose `xdotool key ctrl+v` timed out on a saturated
  X server fell back to re-typing 1127 accented chars → corruption + a
  3-min MappingNotify keymap storm; **non-ASCII typing** on a us-layout
  remapped the keymap per char, freezing the whole desktop
- Whisper repetition loops collapsed deterministically (#24)
- Historique submenu flash-and-close: never rebuild a DBus-exported menu
  while shown — eager, change-aware rebuild (#12)
- Keyboard lock during typing: explicit modifier keyup, dropped
  `--clearmodifiers` (xdotool#43) (#13)

### Infra
- Single-instance flock; in-place `execv` restart (take-safe); launch via
  `systemd-run --user` so stdout reaches journald; line-buffered stdout;
  GUI-stall watchdog prints `GUI stall: blocked ~Xs`
- Open-sourced: identity scrub (filter-repo mailmap), repo flipped PUBLIC,
  MIT, v0.1.0 release + `curl | bash` installer, GitHub Actions CI (#16-#19)

### Doctrine
- **No denoising**: Whisper is noise-robust by design; over-cleaning adds
  artifacts and hurts the decode. Quiet speech needs *level*, not cleaning.
- **No type-fallback for paste-destined text**: typing long/accented text
  on a mismatched layout corrupts it AND triggers the keymap-remap freeze.
- **`multilingual=True` is the code-switch switch**, not language-forcing.
- **Forensics before theory**: read the journal `take:` breakdown + history
  DB telemetry first; three freezes were misattributed before the journal
  named the real cause. faster-whisper exposes `avg_logprob`+word probs
  natively (no spaCy ever installed) — perplexity is one field away.

## Sprint 1 — 2026-06-11 · Première dictée: from empty dir to GPU-powered dictation

### Added
- Poetry scaffold, `src/tuparles` layout, architecture README (#scaffold)
- Bilingual spoken-punctuation post-processor with protected-phrase
  shielding ("virgule"→`,`, "rond-point" survives) — 27 tests (#punctuation)
- Demo spine daemon: Right Ctrl+Alt tap-toggle → mic capture → transcribe
  → punctuate → xdotool type into focus + clipboard (#1, #3-partial, #5)
- `GpuEngine`: persistent faster-whisper large-v3-turbo fp16 on the
  RTX 4080 — 29x realtime, ~1 s for a 20 s utterance (#spike)
- `QwenCpuEngine` fallback: vendored antirez/qwen-asr C binary (#spike)

### Fixed
- notify-send blocking daemon threads for 5 s (fire-and-forget Popen)
- Glued sentences from ASR ("question.Alors" → "question. Alors")
  without breaking filenames/decimals
- xdotool typing delay 12→2 ms (long transcripts felt like a UI freeze)

### Infra
- vendor/qwen-asr built from source (OpenBLAS, AVX); Qwen3-ASR-0.6B
  weights in models/ (both gitignored)
- Scoped permission: .claude/settings.local.json allows the vendored
  qwen_asr binary + its make builds, nothing broader
- cuBLAS/cuDNN via pip wheels with ctypes preload — no system CUDA

### Doctrine
- docs/spike-backend.md: full backend matrix. Whisper-family pays a fixed
  ~30 s encoder window per call on CPU; qwen scales with audio length;
  interactive streaming drowns on CPU. All moot once the RTX 4080 was
  discovered idle — GPU turbo is primary, CPU is fallback.
- Live partials design: re-decode the whole growing buffer ~1 Hz on GPU
  (≤1 s per call) instead of any VAD-segmentation pipeline.
