# Changelog

## Sprint 8 — 2026-06-24 · Cartographier les prochains fronts (research + roadmap)

### Research
- **Local PII firewall** (`docs/research/2026-06-24-local-pii-firewall.md`,
  #102) — three parallel research angles synthesized: rent detection
  (`python-stdnum` + ONNX GLiNER, no torch) + Presidio operators; own the spine
  (policy router, in-RAM map that never hits disk, fail-closed interlock,
  code-symbol allowlist from the dict-seed AST). Three layers / three safety
  semantics; sanitize-before-LLM as the new edge.
- **Roundtable speaker ID** (`docs/research/2026-06-24-roundtable-*.md`, #108) —
  diarization (pyannote community-1 + sherpa-onnx no-torch fallback),
  enrollment+ID (CAM++ + τ/δ abstain interlocks), name-from-ASR binding,
  DER/cpWER eval, GDPR Art.9 + EU AI Act "not remote" escape. A sherpa-onnx
  addendum folded into the diarization SOTA note (escapes the WhisperX torch-pin).

### Added
- **Roadmap**: two epics + 13 children (#102–#114), dependency-wired, phased
  MVPs and standalone entry points (#103 / #104 / #39 / #113). #39 refreshed to
  the diarization SOTA verdict.

### Doctrine
- **Cross-epic leverage**: build the PII firewall's erasure path first → the
  roundtable's biometric-delete (#112) is nearly free. The dict-seed AST (#54)
  feeds both the PII code-allowlist (#106) and the roundtable name-lexicon (#110).
- **Voiceprints are biometric PII** — the firewall's local-only / consent /
  easy-delete doctrine carries straight into roundtable mode.

## Sprint 7 — 2026-06-24 · Le miroir local

### Added
- **Telemetry primitives** (`src/tuparles/telemetry/`, #97) — a small modular
  layer mirroring `nlp/`: `event()` / `timer()` gated by a local opt-out, a
  sibling `events` table in the existing data store (additive migration,
  history's rows untouched), and `readout` aggregations. Synchronous writes;
  local-only by doctrine.
- **Feature instrumentation** (#98) — three discovery surfaces emit events:
  `command.fired`, `syntax.used` (only when a feature actually changed the
  text, via a pure `on_fire` hook threaded daemon → `postprocess` →
  `apply_syntax`, so the eval path stays side-effect-free), and
  `entry.dictation` (hotkey vs tray). Mode-switch waits on #47's feature.
- **nlp-over-introspection adapter** (#100) — utterances (`history.texts` →
  `message_documents`) yield a tag cloud + YAKE keyphrases; the event log is
  summarised by the readout. Degrades to empty (never crashes) without the
  `nlp` extras.
- **Analytics dashboard** (#101) — a tray *Analytics…* window, three views:
  *Ton usage* (feature counts + the discovery gap), *Ta voix* (tag cloud +
  keyphrases over your dictations), *Ton code* (the cached codebase EDA,
  rendered from disk — never computed live, so the GUI never freezes and #70
  isn't a blocker). Live re-analysis is a worker-thread fast-follow.

### Changed
- **Privacy is a setting** (#99) — a *Confidentialité* section in *Réglages*:
  default-on local usage tracking, a master kill-switch, and an "effacer mes
  statistiques" wipe behind a confirmation. Smart local default, total override.

### Doctrine
- **Telemetry is introspection, not analytics.** Single-user, local-only, no
  consent or transport layer to get wrong. The question it answers — *which
  features earn their place?* — feeds deletion-beats-addition.
- **Never freeze the GUI for data.** The corpus view renders cached JSON
  instead of building a 50k-term corpus on the GUI thread (the stall watchdog
  would catch it); the cheap views (usage, voice) stay synchronous.

## Sprint 6 — 2026-06-24 · Le moteur qui lit ton code

### Added
- **Corpus-analysis engine** (`src/tuparles/nlp/`, #64–#67) — the foundation of
  codebase-aware dict-seeding (#54). A source-agnostic pipeline: `sources`
  (code / text / chat-history adapters → a typed-term `Document`), `parse`
  (Python + Markdown ASTs with a hierarchical weight table — dep 10, def 6, H1
  5, ident 3, comment 1; manifests yield dep names; other languages a coarse
  sweep), `features` (per-term counts/salience/flags + peak TF-IDF), `signals`
  + `fuse` (symbol / TF-IDF / embedding rankers combined by RRF).
- **Three analysis engines** on that core (`nlp/engines/`): **dictseed** (#54 —
  `whisper_risk` × RRF prominence → STT seed candidates), **keywords** (YAKE +
  KeyBERT-method-on-fastembed + corpus tag clouds), **cluster** (KMeans themes).
- **First real EDA** on TuParles + AlgoliaSaaS (51,652 terms, 39,342
  candidates): `scripts/nlp_eda.py`, `notebooks/dictseed_eda.ipynb`, and a build
  note (`docs/research/2026-06-24-codebase-aware-dict-seeding-eda.md`) seeding
  the blog (#42).

### Infra
- **Quality tooling** brought to the 2026 baseline: **mypy** (CI gate, Qt
  frontend grandfathered), **pytest-cov**, **pre-commit** (ruff + mypy +
  hygiene), stricter **ruff** (I/B/UP/SIM/C4/RUF). Whole tree mypy/ruff-clean.
- **Dependency groups**: light, portable NLP deps (markdown-it / scikit-learn /
  yake) in a CI-installed `nlp` group; heavy embedding backends (fastembed,
  sentence-transformers/torch) quarantined in an optional `embed` group, their
  tests behind an `embed` marker so the cross-OS matrix never touches torch.

### Doctrine
- **Own the spine, rent the algorithms** — no library models code symbols *and*
  their structural provenance, so we keep the thin typed-term/AST spine ours and
  rent TF-IDF/clustering/keyphrases from scikit-learn / YAKE / fastembed.
- **The corpus had opinions, measured before tuned:** raw symbol-salience is
  volume-biased (surfaces `const`/`std`/`the` on a big C++ repo); TF-IDF rescues
  it (0/15 top-list overlap); the three signals are near-independent (|corr|
  ≤0.15, Spearman vs embed ≤0.08) — which is exactly why RRF fusion pays. And
  the embedding **clusters the noise for free** (test/assert macros collapse
  into their own cluster), pointing at cluster-based denoising over a stoplist.

## Sprint 5 — 2026-06-24 · Mesurer le code-switch, et poser la grammaire parlée

### Added
- **Adversarial code-switch eval suite** (#51) — a reproducible yardstick for
  the bilingual moat. An 18-case corpus of FR-EN traps (English verb-borrows,
  cross-lingual homophones, mid-sentence switches, English numbers, acronyms),
  each declaring the token that *must survive* and the misfire it must *not*
  become — seeded with the real `fan out` → `fais un air` bug that prompted it.
  Multi-engine WAV generation (piper neural + espeak), cross-lingual voicing (a
  French voice on English tokens = the realistic trap), all ffmpeg-normalised
  to 16 kHz mono. Scoring = slot-gate + WER-trend. A GPU-gated integration test
  runs the full pipeline; the scorer + corpus integrity run in CI now.
- **Spoken-syntax core** (#57) — the framework every structured-dictation
  family plugs into: an ordered, settings-gated feature registry with a
  never-crash-the-take contract and a `SyntaxContext` that threads the
  output-format target. The first brick of the spoken-syntax moat (EPIC #53).
- **Spoken quotes** (#32) — first family on that core. Bilingual triggers
  (`ouvre/ferme les guillemets`, `open/close quote`, `unquote`, `entre
  guillemets`, bare `guillemets` auto-alternating, auto-close), configurable
  marks (straight default; guillemets with U+202F/U+00A0 spacing, or curly), and
  a structural pair-guard so a lone spoken "guillemets" stays text.

### Changed
- Extracted `pipeline.postprocess()` so the daemon and the eval harness run the
  *identical* text path (punctuation → lexicon → spoken-syntax → repeat-collapse)
  — a test that skipped post-processing would measure a fiction.
- **Project `CLAUDE.md`** added (#56): the docs-honesty duty (update docs +
  in-product help when big things ship) and the doctrines now guiding the moats.

### Doctrine
- **You can't improve a moat you can't measure.** The eval suite is the
  substrate the #49 fine-tune and #34 validation presuppose; synthesised
  franglais is a reproducible proxy, real recordings drop into the same scorer.
- **Safety is structural, and lives in the feature.** The syntax core provides
  the place to hang an interlock + the never-crash contract; each family brings
  its own (quotes' pair-guard). When in doubt, it's text.
- **"It's a setting" — smart default, total override.** Every syntax knob ships
  a sensible default and a Réglages toggle; we don't argue the One True Default.
- Design program tracked as four epics with dependency chains: spoken-syntax
  (#53), codebase-aware dict seeding (#54), agentic/MCP (#46), onboarding (#55).

## Sprint 4 — 2026-06-23 · La voix qui commande (sans le cloud)

### Added
- **Voice command meta-language** (#41) — a take is now either text *or* a
  small, fixed, deterministic edit command, never a probabilistic guess. The
  honest local answer to cloud "agent modes": no model, no round-trip, no
  surprises. Bilingual (FR + EN code-switch). Grammar: delete by
  word/char/line/all with degrees ("efface efface trois mots", repetition, or
  explicit count), `annule`/`undo` (chainable), `un peu plus`/`un peu moins`
  nudges the last edit, `ouvre un terminal`. Confirmation toast in the bubble.

### Doctrine
- **Command-vs-dictation safety is structural, not heuristic** (#41): delete
  requires a *doubled* trigger ("efface efface") — nobody doubles a verb in
  prose, so the doubling *is* the interlock. Plus a length guard (commands are
  terse) and a literal-escape ('dis "efface efface"') that fires only when the
  remainder would itself be a command. Bias is asymmetric and absolute: when in
  doubt, it's text. The test suite leads with an adversarial prose corpus that
  must all classify as non-commands — that corpus is the real spec.
- Edit execution reuses the paste backends (xdotool/ydotool) under the same
  best-effort contract: a failed keystroke is logged, never crashes the daemon.
- Design record: `docs/research/2026-06-23-voice-commands-design.md`. The
  held-modifier "command quasimode" and live/Wayland validation are the
  documented follow-up (#50, behind real-use validation #34).

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
