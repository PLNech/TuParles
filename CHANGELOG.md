# Changelog

## Sprint 28 — 2026-06-29 · Le troisième barreau — whisper.cpp sur CPU

A loose thread from the gradient plan, tied off. The overnight Android session had
extracted a `_CpuPartialsMixin` *for* a whisper.cpp CPU engine that was never
written; this writes it. The point isn't a faster fallback — it's a **promptable**
one: qwen takes no `initial_prompt`, so on CPU the personal glossary couldn't bias
the decode (the documented "pipeline" → "payplane" fumble). whisper.cpp does, so
the CPU rung now restores exactly the vocab bias the GPU has. And because ggml does
runtime SIMD dispatch, the one source spans no-AVX2 x86 and ARM NEON — the engine
the Pi-class home host runs (`docs/research/2026-06-28-stt-host-decision.md`).

### Added
- **`WhisperCppEngine` — the promptable CPU rung** (#4) — whisper.cpp via
  pywhispercpp, sharing the small-model live partials (`_CpuPartialsMixin`) with
  qwen but with a *promptable* final decode: glossary + carryover context ride
  `initial_prompt`, like the GPU path. Language maps selection→`auto`/forced
  (whisper.cpp has no per-segment multilingual flag — the GPU stays the code-switch
  ceiling, stated honestly); the code-switch language is borrowed from the partials
  model, qwen-parity (#10). The whisper.cpp model is injectable, so prompt/language
  logic is tested without the native build.
- **`whispercpp_model` setting + `WHISPERCPP_MODEL`/`_THREADS` config** — smart
  default (`base`), total override; `small`/`medium-q5` for a capable host.

### Changed
- **CPU rung is now chosen, not fixed** (#4) — `_cpu_fallback_factory` prefers
  whisper.cpp when it imports AND a model loads, else qwen. Both `load_engine` and
  `ResilientEngine` route through it. The pywhispercpp import is lazy (fires only
  when the CPU rung is actually built), so the lean/GPU install never pays for the
  native build — and with the dep absent, behaviour is byte-identical to before.

### Infra
- **Optional `whispercpp` poetry group** (root + desktop dist) + a `whispercpp`
  pytest marker, deselected by default — the lean/CI suite never needs the native
  build. 8 deterministic fake-model unit tests (prompt composition, language map,
  empty-audio guard, partials delegation + provenance, the fallback chooser both
  ways) run in the default suite; one marker-gated smoke test decodes on the real
  ABI for whoever installs the rung. **Full suite: 801 passed.**

### Doctrine
- **The quality bar is deferred, not claimed.** The plumbing is proven (logic by
  fakes, ABI by the gated smoke test); whether the prompt bias actually restores
  "pipeline" over "payplane" at ≤1× RTF is a *real-hardware* measurement against the
  code-switch eval (#5b/#19) — never asserted from a fake. *Measure before you
  trust.*

## Sprint 27 — 2026-06-29 · La poche — TuParles devient une app

The spike grew a body. What was a build-ladder proof (mic → whisper → postprocess
on the phone) became something you can actually live with for a week off-grid: a
pure-TuParles **keyboard** that dictates into any app, a **scratchpad**, a
home-screen **widget**, a system **recognizer**, a full **Réglages** screen — and,
underneath, the move that made it trustworthy: compute left the UI thread and moved
into a **foreground service**, so rotating the phone mid-take can no longer eat your
words. The design rule throughout: a feature that touches disk, the mic, or the
network ships its **private-mode off-switch** in the same change, and every metric
carries shape, never the text.

### Added
- **The TuParles keyboard** (#16, A2) — an `InputMethodService` that commits
  postprocessed dictation into any app's focused field, with a live meter, language
  cycle, and edit keys. The same core, model, and telemetry as every other surface.
- **Scratchpad home + copy tooling** (#17, A3) — the launcher screen: dictate or type,
  copy/share/clear, pick the model/language, flip private mode — a thin observer of
  the service, never the compute itself.
- **Takes history + the learning loop** (#23, A9; #24, A10) — a durable per-take store
  ({raw, clean, corrected, vote} + profiling) made visible as a newest-first
  **Historique** screen with 👍/👎/✏️ labelling, plus a keyboard **📝 record-fix** key:
  dictate, correct the phrase in any keyboard, return to TuParles, one tap captures the
  field's final form as the take's correction. The week becomes training data.
- **Full Réglages screen + decode-thread knob** (#22, A8) — engine/model/language,
  privacy block (private mode, save-audio, analytics + verbose opt-outs), and a real
  perf knob: thread count flows Settings → `Dictation.decode` →
  `WhisperContext.transcribeData(threads)`, 0 = auto (high-perf cores), an override
  clamped to the core count. A live whisper SIMD/core readout answers "what am I
  running on?".
- **Smart home-screen widget** (#19) — one-tap dictate without opening the app; the
  service mirrors live state onto it and delivers the result to the clipboard plus a
  tap-to-open notification (so it lands even where background clipboard writes are
  gated). Update spam damped to a per-face dedup for battery.
- **System recognizer** (#19, A5) — `android.speech.RecognitionService` over the shared
  decode path: set TuParles as the device voice input and the mic-button anywhere goes
  on-device instead of the cloud. A 30s safety cap never holds the mic open.
- **Realtime feedback while recording** (#20, A6) — per-chunk RMS meter + timer painted
  from the recorder, surfaced on every face (scratchpad, keyboard, widget).
- **Typed analytics attributes** (#25, G) — `metric(name, Map<String, Any?>)` keeps
  Int/Long/Double/Float/Boolean as native JSON types end-to-end, so the domovoy
  duckdb/NLP layers chart numbers as numbers. Mirrored into the Domovoy repo.

#### Hardening pass (reliability for a week offline)
- **Stop action on the recording notification** (#26) — end a take from the shade
  without opening the app; shown only while recording.
- **Real history export** (#27) — Historique exports `takes.jsonl` via the share sheet
  (FileProvider) instead of only toasting; the learning data is portable.
- **Record/decode guards** (#28) — RECORD_AUDIO checked in the service (the widget +
  recognizer have no UI to ask) → clean error, never a silent dead mic; a 180s recording
  safety cap; idempotent stop; `AudioRecorder` throws on an uninitialised mic.
- **Data management in Réglages** (#30) — storage readout for history/audio/logs, each
  clearable behind a confirm dialog.
- **Decode heartbeat** (#31) — `Decoding` ticks elapsed ms so a long (small/medium model)
  decode reads as alive, not frozen.
- **First Kotlin-side unit tests** (#29) — framework-free helpers extracted to `Text.kt`
  (levenshtein, humanBytes, meterBar); 8 pure-JVM tests, no Robolectric. Version bumped
  `0.1-spike → 0.3.0`.

### Changed
- **Compute moved into a foreground service** (#21, A7) — recording AND decoding now run
  in `DictationService` (type `microphone`), independent of any Activity/IME lifecycle.
  The surfaces observe a process `StateFlow`; a take in flight survives rotation,
  backgrounding, and "don't keep activities". This is the structural fix, not a
  band-aid.

### Fixed
- **The lost-take bug** (#21) — root cause was decoding inside an Activity's
  `lifecycleScope`, cancelled on configuration change. Moving compute to the service
  (above) plus persisting scratch text + last-consumed-take-id across config changes
  closes it by construction.
- **Freshly-placed widget had no click intent** — the per-face dedup could skip wiring a
  newly placed widget; `onUpdate` now bypasses the cache.
- **Foreground-service start contract** (#28) — the new permission bail-out must still
  call `startForeground` first, or `startForegroundService` throws
  `ForegroundServiceDidNotStartInTime`; go foreground before any early return.

### Infra
- **Privacy is structural in the manifest** — no `INTERNET` permission in release, by
  design; a debug-flavor overlay carries it only for domovoy sync. The durable
  analytics outbox drains when reachable, holds locally otherwise.
- **Private mode is a master switch** — when ON, debug file logging, analytics/sync, and
  raw take audio are ALL suppressed; the user's own dictation result is never withheld.

### Doctrine
- **A feature that wants the mic/disk/network ships its off-switch in the same change.**
  Private mode isn't a screen you add later; it's a parameter of every new behaviour.
- **Telemetry carries shape, never content.** Char counts, edit distance, RTF, votes —
  the learning signal's magnitude travels; the dictated text stays on the box.
- **Every surface is a thin face over one backbone.** Keyboard, scratchpad, widget,
  recognizer all toggle the same service and observe the same state — they cannot
  diverge in behaviour, model, or postprocess.

## Sprint 26 — 2026-06-28 · Le déménagement — `tuparles-core` quitte le nid

Step 5 of the refactor, the one the gate was built to protect: the portable IP
physically left `src/tuparles/` and became its own distribution. The boundary is
no longer a promise enforced by a test — it is two packages that pip can install
apart. Imports did not change; the namespace did not change; the app still runs.

And with the boundary real, step 6 followed: the postprocess literal tables left
Python for packaged JSON — the first shared-data SSOT a future Android consumer reads.

### Added
- **Postprocess tables externalised to packaged JSON** (#11, step 6; approach from
  PR #11) — `LEXICON`, `SPOKEN_TO_SYMBOL` (ordered), `PROTECTED_PHRASES` now live in
  `packages/tuparles-core/src/tuparles/data/postprocess-data.json` (schema_version 1),
  loaded at import via `importlib.resources` (wheel- and Chaquopy-safe; shipped in the
  `tuparles-core` wheel via poetry `include`). Regex compilation and all behaviour stay
  in Python — only literal data moves, so it's one source of truth without a divergent
  parser. The JSON was regenerated from the live tables (not copied from the PR, whose
  `SPOKEN_TO_SYMBOL` predated the 3 hyphen rules), and a consistency test asserts the
  loaded tables match. Behaviour byte-identical: lexicon / punctuation / codeswitch green.

### Changed
- **Monorepo split into two distributions** (#10, step 5) — `src/tuparles/` is gone;
  the tree now lives under `packages/`: **`tuparles-core`** (the 36 portable modules:
  postprocess chain, privacy firewall, voice-command grammar, settings, telemetry,
  history) and **`tuparles`** (desktop: GUI, daemon, engine gradient, audio, hotkey,
  delivery, the optional `nlp/` layer). Desktop path-depends on core (`develop=true`).
- **Shared `tuparles.` namespace via PEP 420** — both distributions populate one
  import namespace, so every `from tuparles.<x> import …` is byte-for-byte unchanged
  across desktop, tests, and Android's `getModule("tuparles.pipeline")`. There is
  intentionally no `src/tuparles/__init__.py` in either package (the version comes from
  `importlib.metadata`, where `bugreport.py` already read it). Verified: a Poetry-2.2
  editable install of both, and a standalone `tuparles-core` wheel, both import clean.
- **Root `pyproject.toml` is now a `package-mode=false` workspace** — owns the dev /
  nlp / embed groups and all tool config (pytest, ruff, mypy, coverage), so
  `poetry install [--with nlp|embed]`, `pytest`, `ruff`, `mypy` all run unchanged from
  the repo root over the whole tree. Tests stay unified at `tests/`.
- **Android Chaquopy mounts core-only** — `srcDir` now points at
  `packages/tuparles-core/src`, so the heavy desktop modules no longer sit on the
  Android Python path at all (they were dead bytecode before).

### Fixed
- **Layout-independent repo-root + data paths** — `config.REPO_ROOT` (vendor/, models/,
  vocab.txt, docs/, CHANGELOG) now walks up to the `.git` marker instead of a fixed
  `parents[2]`, and `telemetry/introspect.py` walks up to find `docs/research/data`
  instead of `parents[3]`. Both survived the two-levels-deeper move; both degrade
  gracefully to a sane fallback / None off a checkout.

### Infra
- **`telemetry/dashboard.py` → `telemetry_dashboard.py`** (#10) — the only Qt module in
  the otherwise-all-core `telemetry/` package; relocated so each subpackage lives wholly
  in one distribution (a regular subpackage can't straddle two editable src roots).
- **Boundary gate widened to 35 modules** (#10) — added `syntax_features.slashes` and
  `privacy.eval` (both post-audit, both boundary-clean) so the CI fence stays honest.
- Tooling taught the new layout: ruff `known-first-party=["tuparles"]` + `src` roots;
  mypy `mypy_path` + `explicit_package_bases` so per-module overrides still match.
  788 passed, ruff + mypy clean — no behaviour change, no code churn beyond the paths.

## Sprint 25 — 2026-06-28 · Un cœur, quatre façades — les choix d'architecture

A planning session turned four open questions into committed decisions: the UI
direction, the core/frontend split, the Python↔whisper.cpp boundary, and the order
of work. No product behaviour changed; what shipped is the design record and the
first spine artifact — the import-boundary gate that the whole refactor leans on.

### Added
- **Import-boundary gate** (#10) — `tests/test_core_boundary.py` imports all 33
  intended-`tuparles-core` modules in a fresh interpreter with the desktop-hard deps
  (PySide6, sounddevice, faster_whisper, pynput, evdev, numpy) *blocked* at the
  import system. All green: the ~2,864 LOC of postprocess/privacy/settings IP is
  genuinely stdlib-only, so the extraction won't fight hidden leaks. This is the
  invariant that keeps the boundary from rotting as steps 4-5 proceed.
- **The transcription contract is core** (#10, step 4) — `Word` / `Transcription` /
  `words_from_segments` + a new `TranscriptionEngine` Protocol live in
  `tuparles/transcription.py` (stdlib-only; numpy only under TYPE_CHECKING). Frontends
  depend on the Protocol, not on a concrete engine — so the gradient (CUDA → qwen →
  whisper.cpp) swaps the impl without touching a caller. Re-exported from `engine.py`
  for back-compat.
- **Static config-boundary gate** (#10, step 5) — `test_core_boundary.py` now also
  AST-parses every core module and fails if it imports the *desktop* `tuparles.config`
  (REPO_ROOT / IS_WAYLAND / QWEN_* / HOTKEY_*) instead of the portable `config_core`.
  The runtime gate can't catch this while `config.py` is still stdlib-only; the static
  gate makes the regression fail now, not after the namespace move turns it fatal.
- **CPU STT bench harness** (#3) — `scripts/bench_cpu_stt.py` runs the same adversarial
  code-switch corpus the GPU eval uses, through the same `pipeline.postprocess` path,
  but on CPU under a realistic core budget (`taskset -c 0-5`, 30% of the machine). It
  is **registry-driven**: a small `EngineSpec` table (name, rung, lazy factory,
  availability probe) is the local seed of the core engine registry (#14), so adding a
  rung is one spec line. Streams JSONL + emits a quality×speed PNG. whisper.cpp-q5 is
  left as an honest, probe-gated gap pending #4 (pywhispercpp) — no faked row.

### Changed
- **Settings path is injectable** (#10, step 2) — `TUPARLES_CONFIG_DIR` points the
  config dir straight at a chosen path (Android app storage, a server container, a
  test); unset = unchanged XDG behaviour. The seam that lets the same `settings.py`
  run off-desktop. (Now factored through a shared `settings.config_dir()` so every
  per-user file resolves to one place.)
- **Glossary path is portable** (#10, step 5) — `vocab.py` dropped its import of the
  desktop `config.VOCAB_FILE` and now defaults to the shared config dir via
  `settings.config_dir()`. Dependency inverted: the desktop CLI keeps its historical
  repo-root `vocab.txt` by passing that path explicitly. Core stays checkout-free;
  Android / server / tests get a real per-user location for free. No data moved,
  desktop behaviour byte-identical.
- **`partials.py` reads `config_core`** (#10, step 1) — repointed off the desktop
  `config.py`, so the partials sanity filter sits cleanly below the core boundary.

### Doctrine
- **One core, four thin frontends** (#10-#13) — commit to the full split:
  `TuParles.app` / `tuparles-service` / `tuparles-server` / `tuparles-android` over a
  pure-Python `tuparles-core`. `.app` and `-service` are one desktop runtime (GUI
  optional). Config = one Python-authored schema → committed `settings.schema.json`
  SSOT → generated Kotlin (CI diff-gated). Shared logic travels as Python (Chaquopy);
  shared data as JSON; native idioms (`strings.xml`) are generated, never duplicated.
- **The UI framework isn't where the hard parts live** (#13) — global hotkey,
  always-on-top, and text injection are Wayland *protocol* problems (GlobalShortcuts
  portal / `wlr-layer-shell` / ydotool) that hit every toolkit equally and live in our
  layer regardless. So the UI is chosen on rendering + cross-device reach: finalists
  **pywebview** (lean) vs **PySide6+QML**, resolved by a spike. `always-on-top` as a
  window flag is a Wayland no-op for everyone; GNOME refuses layer-shell → reduced HUD
  mode there (graceful degradation).
- **pybind over hand-bindings unless measured otherwise** (#4) — Python↔whisper.cpp
  on the CPU rung defaults to **pywhispercpp** (in-process, restores prompt-bias +
  word-confidence, same GGML family); ctypes only if the benchmark proves a latency
  margin worth the per-release tax. Both are in-process, so "fastest" rarely separates
  them.
- **Order: arch → engine → UI** — the core boundary makes everything downstream
  cheaper; the engine is the differentiator; UI last, spike-decided.
- **The platform is its own bench** (#14) — STT engines (CPU/GPU/embedded) will be
  swapped and upgraded repeatedly, so engines are named, pluggable adapters behind the
  `TranscriptionEngine` Protocol, gathered in one registry that *both* the runtime
  gradient and the bench/eval suite consume. Adding the next engine is a registration,
  not a two-place edit. Wired for real when the 3rd engine (WhisperCppEngine, #4)
  forces it; the bench is already registry-driven as the seed.
- **Runtime SIMD dispatch is a portability requirement, not a nicety** (#9 → #4/#6) —
  the SIMD audit found the vendored `qwen_asr` is built `-march=native` with
  *compile-time* AVX2/FMA selection and zero `cpuid` dispatch, so it **SIGILLs** on a
  no-AVX2 host (the 2011 erable i3). CTranslate2 (MKL+oneDNN) and whisper.cpp (ggml)
  both ship *runtime* dispatch with an SSE floor and degrade gracefully. So the public
  CPU rung wants whisper.cpp on portability grounds alone, and the #6 `/stt` shim must
  never hand `qwen_asr` to a no-AVX2 box. "Still works on the train" means the binary
  must ask the CPU what it can do — at load, not at compile.

### Infra
- **CPU STT bench, executed** (#3) — `scripts/bench_cpu_stt.py` run over the 72-WAV
  code-switch corpus at 30% CPU (5 engines × 72 = 360 decodes, 0 errors). RTF rises
  tiny 0.23× → base 0.45× → qwen 0.68× → small 0.97× → large-v3-turbo **4.5×**;
  large-v3-turbo wins WER (0.57) but is **latency-disqualified for live CPU**. Surprise
  of the run: **qwen (the incumbent fallback) Pareto-holds** — 2nd-best WER (0.68),
  faster than realtime (0.68×), and it dominates fw-small on *both* axes. Caveat that
  decides #4: the bench drops the vocab `initial_prompt`, which handicaps the
  prompt-capable whisper family but **not** qwen (qwen takes no prompt) — so
  whisper.cpp's production ceiling sits above its bench line. Concrete bar for #4:
  match qwen's 0.68 WER *with prompt-bias on*, at ≤1× RTF. Chart + summary JSON
  archived (`/tmp/tuparles_cpu_bench.png`).

### Research
- `docs/research/2026-06-28-ui-architecture-decisions.md` — the four forks with the
  why, the Wayland terrain that reframes the UI choice, the core+4-frontends diagram,
  the config/UX-sharing strategy, and the 10-step minimal-refactor path.
- SIMD/build-flag audit (#9) findings recorded in memory `stt-api-and-tuparles-gradient`
  (qwen RED / CT2 GREEN-slow / whisper.cpp portable); the per-engine GREEN/RED verdict
  feeds the #5 host decision and the #6 shim's never-hand-qwen-to-no-AVX2 rule.

## Sprint 24 — 2026-06-28 · La route vers le cloud — recon, pas de code

Two questions, no shipped code: can the Android acceleration work feed back into
the desktop CPU path, and can TuParles' STT live at `api.nech.pl/stt/v1/`? Both
answered as a design + a measurement. The honest output is a research note and a
benchmark to run; the durable wins live there and in session memory.

### Infra
- **Retired the `feat/android-spike` worktree** (#1) — it wasn't a lost repo, it
  was a git worktree already merged into `main` (`bc12fc4`). Removed it + the
  merged local branch; `android/` stays on `main`. A `.git` *file* (not dir) =
  worktree; `git worktree list` before assuming a repo vanished.

### Doctrine
- **The 2-rung ladder is a gradient** (#1) — turbo-GPU / qwen-CPU generalises to
  a 6-rung VRAM→(RAM+AVX+cores) gradient. **whisper.cpp unifies the CPU rungs**
  (musl-friendly, AVX2-graceful, one GGML weight family across Android / erable /
  home-box / laptop-CPU); ctranslate2 stays GPU-only (no musl wheels). qwen-asr is
  on the ballot — retire it if whisper.cpp wins the benchmark at equal quality.
- **The Android wins were mostly learnings, one real port** (#1) — the `-O3` and
  `language="en"` breakthroughs don't port (desktop solved their roots already);
  the carry is adopting whisper.cpp on CPU to restore `initial_prompt` bias +
  word-confidence that qwen dropped, and unify the model family.
- **Measure the box, not just the model** (#2) — `ssh` proved `erable` is a 2011
  i3-2130, no AVX2, ~1.8GB free RAM, already swapping. It hosts the thin `/stt/`
  shim and dispatches heavy decode elsewhere (per the platform's own doctrine);
  it is not the engine. Laptop-tunnel rejected; on-box big-model impossible.

### Research
- `docs/research/2026-06-28-cpu-engine-gradient-and-stt-api.md` — the full why:
  Android-learnings audit, the engine gradient, the `/stt/` API plan (domain,
  thin-container tier, whisper.cpp-not-faster-whisper, WAV-batch-first,
  sha256 caching), erable reality, Redis status, and the benchmark-corpus call
  (synthetic WAVs fine for RTF, weak for real-world WER).

## Sprint 23 — 2026-06-28 · « slash » devient `/` (piloter au clavier-voix) · v0.3.0

You dictate INTO Claude Code, shells, URL bars, code comments. They all spell `/`
the way you say it: "slash". But "slash" decoded as the *word*, and a split
command name ("pre compact", "code review") never rejoined — so the one place
voice should shine, driving a REPL, was the one place it fumbled. Fixed as a
spoken-syntax family (#53), not a model tweak: deterministic, post-decode,
reversible — plus a tiny decode-time seed so Whisper *hears* "slash" at all.

### Added
- **Spoken slashes** (`syntax_features/slashes.py`) — every spoken "slash"
  becomes "/", a path separator that glues to its neighbours: "slash help" →
  `/help`, "endpoint slash habits" → `endpoint/habits`, "code slash slash
  comment" → `code//comment`. A curated **ontology** of Claude Code commands
  canonicalises known names ("slash pré compact" → `/pre-compact`, "slash code
  review" → `/code-review`); accents are trimmed (`/cafe`, not `/café`) and what
  follows a "/" is treated as ASCII. A "/" after sentence punctuation keeps its
  space, so breaks survive ("Bonjour. /help"). Wired into
  `pipeline.postprocess()` (daemon + eval share it); auto-listed in
  `tuparles cheatsheet`.
- **Spoken hyphen** (`punctuation.py`) — "tiret" / "trait d'union" / "hyphen" →
  `-`, so you can spell a command or identifier aloud ("slash pré tiret compact"
  → `/pre-compact`).
- **Command-vocabulary seed** (`seed_prompt.COMMAND_SEED`) — a tiny, validated
  bias so Whisper actually *hears* the command. The 2026-06-28 take replay
  proved it rescues the worst mishear: "slash precompact" decoded as "c'est l'âge
  prix compact" → `/pre-compact`. Rides the protected tail with the manual
  glossary, gated by `dictseed_bias`.
- **`slash_commands` setting** — a flat list extending the ontology with your own
  command names, no source edit. The family as a whole toggles via
  `settings["syntax"]["slashes"]`.

### Doctrine
- **Forensics first: we seeded commands because the replay said to.** The earlier
  instinct was "rewrite, don't seed". But take 16 has *no* "slash" in the decoded
  text to rewrite — it had to be fixed at decode time. So we measured
  (`docs/research/2026-06-28-spoken-slash-commands.md`): a command-WORDS-only seed
  rescues it with zero hallucination, while a URL-example seed *invented*
  `facebook.fr`/`google.com` (the Sprint 13 over-seeding tax, reproduced). Seed
  the commands, drop the URL examples.
- **"slash" means `/` everywhere — a measured product call.** It fires anywhere,
  not just a line head, relaxing the house when-in-doubt-text asymmetry: in real
  dictation (the take forensics) "slash" was the glyph, never prose. The one
  thing we *won't* fuse is a sentence break. It stays a setting.
- **URLs are the harder sibling — deferred to a dictation mode.** "https deux-
  points slash slash …" mangles *acoustically* ("https2…", "slashnek"), so no
  seed or rewrite this sprint fully fixes it. The right answer is a spoken
  spell/URL quasimode (#62-kin), scoped separately rather than hacked in here.

## Sprint 22 — 2026-06-27 · Le POC qui parle dans la poche

The Android spike went from "research epic" to **a working app on a Fairphone 6**
in one sitting: mic → native whisper.cpp → embedded-CPython `postprocess()` → text,
one shared core with the desktop. Shipped as a public experimental APK.

### Added
- **Android experimental POC** (#2) — laddered spike (Rung 0 hello-world → 1
  Chaquopy embed → 2 whisper.cpp JNI → 3 full loop), all verified on-device.
  A 12→15-prompt FR/EN code-switch capture harness (diverse: beatmaking, rap,
  cuisine, gaming, skate, danse…), saving `{wav, raw, cleaned}` per take.
- **Toggles** (it's-a-setting): *Langue* auto/fr/en, *Postprocess* on/off.
- **Local email export** — `📧 dev@nech.pl` via `ACTION_SEND_MULTIPLE` + FileProvider,
  no INTERNET permission.
- **Self-contained APK** — base model bundled in assets (fetched, gitignored);
  prefers a pushed larger model if present. Published as Release `android-poc-0.1`.

### Fixed
- **Native `-O3`** — debug APKs compiled `ggml-cpu`/`ggml-base` at `-O0`, ~50×
  too slow (88s→1.5s for base). Forced `-O3` on every ggml target.
- **`language=auto`** — the grafted JNI hardcoded `params.language="en"`, which
  *translated* French to English. Threaded a language param through; default auto.
  Validated offline with whisper-cli on real recordings.

### Infra
- Recreation-safe model (process-scoped `Engine` singleton + `configChanges` +
  portrait lock); in-decode progress logging; 90s decode timeout.
- Vendored whisper.cpp trimmed to the CPU backend (20MB → 6.2MB).

### Doctrine
- **Measure before you trust** paid twice: the `-O0` slowness and the `en`
  mistranslation were both invisible until instrumented + reproduced (offline
  whisper-cli on the device's own recordings).
- **Every feature degrades** — bundled base for OOTB speed, large-v3-turbo for
  flawless quality; the user picks via a pushed model. GPU-or-CPU, here it's
  fast-or-accurate, runtime choice.

## Sprint 21 — 2026-06-27 · Le cap Android, et la maison d'aplomb

Two strands: chart the course to TuParles-on-Android (research + a
contributor-ready epic), and — found en route — quietly un-red a CI that had
been failing for days without anyone noticing.

### Added
- **Android-readiness research + phased epic** (#2) — a 5-agent research
  fan-out (engine SOTA, packaging fork, codebase portability audit, Android
  platform/privacy) plus an adversarial verification pass, synthesized into five
  build notes under `docs/research/2026-06-27-android-*` and
  `-portable-core-audit.md`. Verdict on #2: embed the pure-Python postprocess on
  Android via Chaquopy (one source of truth), engine = whisper.cpp (ONNX Runtime
  if the doubt/spans UI must launch), gated on a FR/EN code-switch spike. Broken
  into an epic → children #3–#8 with Codex-ready briefs.
- **`config_core.py`** (#4, PR #9) — platform-agnostic constants split out of
  `config.py` (which re-exports them, zero call-site churn) so
  `pipeline.postprocess()`'s import closure carries no desktop deps. First
  portable-core step toward Android. (Authored by Codex, operator-reviewed.)

### Changed
- **Optional `stdnum` import guarded** (`privacy/structured.py`, #4) — the
  checksum validators (IBAN/NIR/card) degrade to no findings when
  `python-stdnum` is absent, byte-identical when present; the firewall loads on a
  lean install.

### Fixed
- **Windows-safe temp WAV in qwen CPU decode** (`engine.py`, #10) —
  `transcribe()` reopened a still-open `NamedTemporaryFile`, which Windows
  forbids (`PermissionError`). Now `mkstemp` + close fd + write-by-path +
  `unlink` in `finally`; identical on Linux/macOS. A real cross-platform bug,
  surfaced by the CI repair.

### Infra
- **CI matrix un-redded** (#10) — `main` had been failing on all six legs,
  masked by one collection error: `test_daemon_finish` imported Qt at module top
  (`Controller(QObject)`), aborting the whole pytest session and hiding latent
  failures in `test_ui_honesty` (pure helpers trapped in the Qt-coupled `ui.py`)
  and `test_cpu_partials` (exec'd the absent qwen binary; Windows temp-wav).
  Guarded the Qt-coupled tests with `pytest.importorskip("PySide6")` (matching
  the `_qt()` convention) and mocked the CPU decode path.

### Doctrine
- **A green local run is not a green CI.** Reproduce CI in a *fresh git clone* +
  clean venv before trusting a pass — a clean venv over your own working tree
  still carries gitignored artifacts (the qwen binary) that CI lacks, so it
  hides failures. A collection-time import error aborts the *whole* suite and
  masks everything downstream; fix it first, then re-enumerate.
- **Codex as workhorse, human as operator.** Drive an external coding agent on
  substantive, verifiable work (it opened PR #9 cleanly); keep incident
  firefighting — where the agent can't even reproduce the condition — on the
  operator. Always review the raw diff and run the real gate; "done, tests pass"
  is a claim, not a verdict.

## Sprint 20 — 2026-06-27 · Le visage honnête

A convenience sprint: small, visible polish that makes the tool *read* honestly —
own its misses, name its fallbacks, and never silently destroy what you'd copied.

### Added
- **Never recant a salvaged partial** (`daemon.py`, `ui.py`, #27) — when a final
  decode is lost but a partial was visibly painted, the bubble no longer red-flips
  to a failure. A new amber **`recovered`** state dissolves the *dimmed partial
  itself* — the words you saw stay on screen — with a `Ctrl+V` badge (it was
  copied) and a longer dwell. Held, not failed. Rides its own `recovered` signal,
  not the red `error` channel.
- **Backend-shift toast** (`daemon.py`, `settings.py`, #27) — the first time a
  decode falls back GPU→CPU mid-session, one toast: *"Passé sur CPU — un peu plus
  lent."* The bars go green→blue regardless; this names it so the change reads as
  honest, not a bug. Sticky (the fallback is) — said once. Setting `backend_toast`
  (default on).
- **Decode-elapsed counter** (`ui.py`, #28) — a decode running past 3 s shows a
  dim `(Ns)` badge in the pill, so a long CPU take reads as *working (12s)*, not
  *frozen?* Injected clock → headless-tested, no sleeps.
- **Clipboard preserve/restore** (`delivery.py`, `settings.py`, #28) — TuParles
  pastes via the clipboard, clobbering whatever you'd copied. With
  `clipboard_restore` on (default **off**), we snapshot the clipboard before
  delivery and put it back after the paste settles — **but only when it's
  genuinely text.** The clipboard is typed: an image or a file list snapshot via a
  text tool is empty, and writing *that* back would destroy the payload. So a
  non-text clipboard is left alone (our pasted text stays) rather than nuked.
  `is_text_clipboard()` rejects image/files/app types (and `text/uri-list`, a file
  list wearing a `text/` prefix) before any text match.
- **Dev raw-audio capture as a visible toggle** (`takes.py`, `settings.py`,
  `settings_ui.py`, `tray.py`, `daemon.py`, #8) — the replay capture
  (`takes/<id>.wav`, *unredacted* voice) is now a Réglages toggle
  (`dev_recording`, default off) with an explicit raw-audio warning, not env-only.
  The earlier "env-only so it can't be flipped by accident" safety is kept
  *differently*: while armed, the tray glyph shows a **steady red dot** and the
  tooltip spells it out, plus a boot-time reminder line — so it can never run
  silently. `TUPARLES_DEV` stays as the override (set = wins, either way).

### Infra
- **Span token-stream model — the doubt-rendering keystone** (`spans.py`, #21) —
  a take's text as a list of `Span` (word/punct/space/newline), each carrying
  `confidence` (None/1.0 = certain), `origin` (decoded/inserted/rewritten/cased/
  collapsed) and `original` (pre-rewrite surface, for never-hide reveal). The
  room a flat string never had for "how sure?" and "what was this before?".
  Load-bearing invariant `flatten(tokenize(t)) == t` is pinned byte-for-byte
  against the code-switch corpus, so the span layer is a lossless *view* — delivery
  and storage (which flatten back to a string) are untouched. Foundation only, no
  user-visible change yet; unblocks the span pipeline (#22) and per-word doubt
  rendering (#16/#24/#26).
- **Cross-env capability probe + explicit fallback chains** (`capability.py`,
  `daemon.py`, #29) — the xdotool-3.x miss showed we *assume* tool capabilities
  instead of probing them. New `capability.probe()` detects, once at boot, what
  this box can actually do — xdotool version + which **subcommands** it supports
  (the exact gap that bit us), xprop/xsel/xclip/wl-copy/wl-paste/ydotool/gdbus,
  X11 vs Wayland — and logs a one-line report (`capabilities: x11 · class=xprop ·
  paste=xsel+xdotool · activate=… · gaps: …`), verbose per-tool in dev mode. The
  detection/fallback CHAINS (window-class, paste, window-activate) are now
  explicit, server-aware, native-layer-first data — each with a *documented*
  fallback, never a silent no-op — and pinned by tests so the formal description
  can't drift from `delivery.py`. Surfaces real gaps immediately (e.g. "clipboard
  restore limited (no type-probe tool)" when `xclip` is absent, tying to #28's
  type guard) instead of after a failed paste. Seeds the build note
  `docs/research/2026-06-27-cross-env-capability-layers.md`.
- **`tuparles diag` + detailed cross-env docs + issue templates** (`cli.py`,
  `docs/CROSS_ENV.md`, `.github/ISSUE_TEMPLATE/`, #29) — `tuparles diag` prints
  the full capability report + environment block to paste into a bug. New
  **`docs/CROSS_ENV.md`** holds the per-setup tool matrix, the X11/Wayland
  fallback chains, and fixes by symptom — the README stays lean and links to it
  (detailed docs in-repo, versioned with the code, not a drifting wiki). GitHub
  **issue forms** (bug/feature + config) ask for the capability line and point at
  the cross-env doc, so reports arrive actionable. Closes the loop: probe →
  report → template.

### Changed
- **Softer empty-decode copy** (`daemon.py`, #27) — a lost final with no partial
  to salvage now says *"Je n'ai pas bien saisi"* instead of *"Rien entendu."* The
  miss is ours to own, not the user's voice to blame.
- **Réglages** (`settings_ui.py`) — two new toggles with tooltips: *Prévenir au
  passage GPU → CPU* and *Préserver le presse-papiers* (incl. its re-paste
  tradeoff). It's a setting: smart default, total override.

### Deferred
- #28's **first-audio pulse** (the live waveform already *is* the "it's listening"
  cue) and **device-switch toast** (more plumbing, a rare event) — left in the
  backlog rather than gilded.

## Sprint 19 — 2026-06-27 · Le doute, le flux, la cible

Building toward the DeliveryTarget keystone — and seeding doubt on the way.

### Fixed
- **Rapid re-press no longer eaten by the chatter guard** (`config.py`,
  `hotkey.py`, `tests/test_hotkey.py`) — the "press again doesn't register for a
  second" gap during back-to-back takes. `HOTKEY_DEBOUNCE_S` was **0.4 s**, but
  the combo edge detector (`_combo_since`) already collapses a single physical
  press to one fire — so the debounce only ever suppressed a *legitimate*
  re-press (a quick start→stop, or stop→start-next). Cut to **0.12 s** (clears
  real switch chatter, allows ~8 toggles/s). A swallowed press now logs
  `hotkey: press ignored, debounce Ns`, and a `toggle ignored: _stopping` line
  covers the teardown window — so the next "didn't register" is a measurement.
- **Window-class detection works across xdotool versions** (`delivery.py`,
  `daemon.py`, `tests/test_delivery.py`) — the *real* "un sur deux" delivery bug:
  `xdotool getwindowclassname` doesn't exist on xdotool 3.x (the box here ships
  3.20160805 → `Unknown command`), so *every* class read silently returned empty
  and **terminals got plain Ctrl+V** — a no-op control char in a tty, the
  "nothing pasted" misses. Class now reads via **`xprop -id <id> WM_CLASS`** (base
  X11, present everywhere), so kitty/gnome-terminal/Claude-Code are detected and
  get Ctrl+Shift+V. Not a queue regression — a long-standing latent assumption,
  surfaced by the new forensics. `window_id` was always fine (`getactivewindow`).
- **Delivery lifecycle forensics** (`daemon.py`) — one journal line per take from
  *armed* (the request: source + target window/class) → *queued* (audio, mode,
  pending depth) → *delivered* (chars, lang, mode, target) or *miss*. Plus
  `deliver.done` / `take.miss` telemetry events: `entry.dictation` minus
  `deliver.done` = the deliveries that went missing, by mode. Records **push-to-
  talk (hold) vs toggle** per take, so the next delivery failure is a measurement,
  not a guess.
- **Dictated newlines reach submit-on-Enter inputs** (`delivery.py`,
  `settings.py`, `tests/test_delivery.py`, #5) — "à la ligne" → `\n` was kept in
  storage but a pasted lone LF is *swallowed* by Claude Code / chat inputs (paste
  LF = eaten; press Enter = submits). Newline pieces now emit a **keystroke** for
  non-`lf` modes (layout-blind keyname, never per-char injection — stays clear of
  the keymap-remap freeze). `newline_mode` setting: `auto` (default — `lf`
  everywhere except known GUI chat apps, which get Shift+Enter) | `lf` |
  `shift-enter` | `enter`. A chat-TUI-in-a-terminal (Claude Code) is
  indistinguishable from a shell by class, so dictating there: set `shift-enter`.

### Added
- **Queue chips — the backlog made visible** (`ui.py`, `daemon.py`,
  `settings.py`, `tests/test_queue_chips.py`, #15) — a small strip of pills above
  the bubble, one per take still decoding in the queue (#14). The main bubble
  shows the take you're speaking now; these show how many earlier takes are still
  cooking and flash each as it lands (a brighter pulse of the backend hue — green
  stays GPU — then it fades). Rides the new `queued`/`delivered` signals; lazily
  built (single-take users never instantiate it); opt-out (`queue_chips`). The
  colour decision is a pure `chip_color()`, headless-tested; the strip's model is
  tested offscreen. Rendering wants your eyes on a live overlap to confirm.
- **FIFO decode queue — capture and decode, decoupled** (`daemon.py`,
  `delivery.py`, `settings.py`, `tests/test_daemon_finish.py`,
  `tests/test_delivery.py`, #14) — a toggle-stop no longer holds the next take
  hostage to the decode. `stop()` now runs off the GUI thread, ENQUEUES a
  `_QueuedTake` (its own audio + `DeliveryTarget` + partial), and frees the
  recorder the instant it returns; one persistent worker drains the queue in
  order. So: *speak, send, speak again* — the next take starts while the last is
  still decoding. Each take delivers to its **origin window** (`deliver_to:
  origin`, X11): if focus actually moved since you spoke, it refocuses the
  dictation window, pastes, then hands focus back where you are — no overlap, no
  dance. Structural depth cap (`queue_depth_cap: 5`): a wedged engine can't pile
  up audio; the cap-th take is refused with a "File pleine" toast, never a silent
  drop. Onset-carryover (#18) still works — better, even, decodes being strictly
  sequential now. Mini-bubbles (#15) ride the new `queued`/`delivered` signals.
- **`DeliveryTarget` — capture-time destination** (`delivery.py`, `daemon.py`,
  `tests/test_delivery.py`, #13) — the window a take was dictated into, snapshotted
  at take-START: `wm_class` (paste combo + newline mode) and, on X11, `window_id`.
  The keystone for origin-window paste once takes deliver asynchronously (the
  queue, #14) — a take pastes back where it was spoken, with that window's newline
  semantics, even after focus moved on. Behaviour-equivalent today (one window per
  sync take); `deliver()` accepts a `DeliveryTarget` (or a bare class, back-compat).
- **Per-word confidence** (`engine.py`, `tests/test_word_confidence.py`, #23) —
  `Transcription` gains `words: list[Word] | None`; the GPU decode now requests
  `word_timestamps` and a pure `words_from_segments()` flattens faster-whisper's
  per-word `probability` into the model. None on engines that don't expose it
  (qwen runs `--silent`) — the doubt UI degrades to no-dimming, never breaks. The
  cheap foundation the rendered-doubt span work (#16/#24) stands on.
- **Onset context-carryover** (`engine.py`, `daemon.py`, `settings.py`,
  `tests/test_carryover.py`, #18) — the first words of a take are the least
  reliable (no left-context — "on vient" → "rien"). A take starting within
  `context_carryover_window_s` (25 s) of the last delivery now feeds that tail
  (capped 160 chars) into the decode's `initial_prompt`, so Whisper has the
  missing context — exactly what helps a re-dictation after a delete. Advisory
  only (never forces a decode, like dict-seed bias), default on, opt-out;
  GPU-only in practice (qwen takes no prompt). Pure `carryover_context()` +
  `_compose_prompt()` are headless-tested; worth an eval pass on real takes.

## Sprint 18 — 2026-06-27 · Forensics sur les ratés

You hit "Rien entendu" while partials were visibly painting text — and we had
*nothing* to show for it. An empty final decode records no history row, so no
id-keyed WAV, and the forensic print only reached the launching terminal. The
one failure most worth debugging left zero trace. Plus, on CPU every take's
language was blank — qwen runs `--silent`, so the code-switch signal that is the
whole point of this tool went dark on the fallback path. This sprint makes the
ratés observable.

### Added
- **Miss capture** (`takes.py`, `daemon.py`, `tests/test_takes.py`, #10) — an
  empty final decode now saves its audio (dev mode) to `takes/misses/miss-<ts>.wav`
  and prints a forensic line (`miss: Ns audio, empty final | raw=…,
  last_partial=… | decode Ns`). The audio you most want to replay is no longer
  the one we throw away. Own 64 MB byte-budget, self-pruning like the takes dir;
  microsecond-stamped names so two misses in a second can't collide.
- **CPU take language** (`engine.py`, `tests/test_cpu_partials.py`, #10) — qwen
  emits no language, so `QwenCpuEngine.transcribe` now borrows the CPU-partials
  model's last detection (`CpuPartialsEngine.last_language`). History `lang`/
  `lang_prob` columns finally populate on the fallback path. Honest about
  provenance: it's the small model's guess, a signal not ground truth; `None`
  when partials are off.
- **`replay_takes.py --engine cpu`** (#10) — the drift harness was GPU-only; now
  it runs the vendored qwen binary too, so you can replay your real takes with
  the card wedged, through the engine that actually served you. qwen takes no
  initial_prompt, so the CPU path skips the seed regimes and does one decode per
  take.

### Fixed
- **Long-take freeze: stop() off the GUI thread** (`daemon.py`, `audio.py`,
  `tests/test_daemon_finish.py`, #10) — a long take froze the whole UI (bars
  and partials stuck) then paste-dumped seconds later. Forensics (the new
  `stop_s`) caught `recorder.stop()` blocking the GUI thread 65 s while the
  decode was 1 s — an *episodic* PortAudio teardown stall (NOT length-driven: a
  longer take stopped in 0.03 s). The stop AND the decode now run on the worker
  thread; the GUI only flips state and returns, so the bubble stays live through
  a stall. A `_finishing` guard serializes the three stop entry points
  (toggle/Esc/combo-release) so a fast second press can't race the teardown.
  `recorder.stop()` is sub-timed (pa_stop/pa_close/concat) and shouts the
  breakdown only when slow, to fingerprint the next stall — it can't be
  reproduced from a captured WAV (replay bypasses the recorder).
- **Doubled-punctuation collapse** (`punctuation.py`, `tests/test_punctuation.py`,
  #6) — saying "virgule" while Whisper also heard the pause emitted "test, ," ;
  a comma butting a stronger mark ("poème, .") was swallowed by it. `_tidy` now
  collapses a redundant comma — comma-only and exact, never merging different
  marks (`?!` stays) nor touching `…`/`...`.

### Added (cont.)
- **Ellipsis "trois petits points" + the real `…`** (`punctuation.py`, #7) — the
  colloquial name now maps to a typographic ellipsis (U+2026), as do the formal
  "points de suspension" and "dot dot dot" (was `...`). Determiner-shielded: "les
  /des/ces… trois petits points" is talking *about* the ellipsis, so it stays
  text — only a bare one is dictation. When in doubt, it's text.
- **Partial recovery belt** (`daemon.py`, #10) — when the final decode is *lost*
  (an exception, or empty while a partial was visibly painted), the last partial
  is copied to the clipboard with a toast (`Ctrl+V`), never auto-pasted — the
  final is the truth and a provisional isn't it. A net for true crashes; the
  screenshot freeze actually landed fine, so this is belt *and* braces, not the
  freeze fix.
- **Persistent heartbeat** (`daemon.py`, #10) — the GUI-stall watchdog only logs
  once the main thread *resumes*, so a whole-system freeze ending in a reboot
  kills us before it fires. A plain-thread `hb:` beat every 15 s (up / rss /
  gui_lag) lands in journald, which survives reboots: after the next freeze the
  last beat dates when we went silent, and `gui_lag` separates a GUI-only hang
  (beats flowing, lag high) from a whole-box freeze (beats stop cold). Was the
  laptop us? Next time we'll know.

### Doctrine
- **The failure you record least is the one you most need.** Instrumentation
  bias should be inverted: a clean landed take is self-evident; a miss is a
  mystery, so it deserves *more* trace, not none. Forensics before theory only
  works if the forensics survive the failure.

## Sprint 17 — 2026-06-26 · Les partiels font le ménage

Live partials sometimes flash junk — silence hallucinations and the canonical
YouTube-caption ghosts Whisper loves ("Merci.", "Sous-titres réalisés par…",
"Thanks for watching"). We suppress them, structurally, without ever rewriting
a word.

### Added
- **Partials sanity filter** (`partials.py`, `tests/test_partials_sanity.py`,
  #3) — a pure `sanitize_partial(segments)` both partial paths (GPU and CPU)
  share, so they can't diverge. Drops a segment only on the decoder's own
  signals — Whisper's no-speech test (`no_speech_prob > 0.6` *and*
  `avg_logprob < -1.0`), a repetition-loop ratio (`compression_ratio > 2.4`),
  bracketed sound-tags (`[Music]`, `♪…♪`) — plus an exact-phrase denylist of the
  confident caption ghosts. Whole-segment match only, never substring, so
  "merci beaucoup" survives. 12 headless tests (the GPU path can't run with the
  card wedged; the pure function still gets covered).
- **Shorter CPU-partials window** (`engine.py`, `daemon.py`, `settings.py`,
  `cpu_partials_window_s`, default 6 s) — the `base` model picks ONE language
  per decode window, so a long French-dominant tail Frenchified the English you
  just switched into ("je suis au traducteur ici"). A short window lets the
  *current* language dominate, so the preview tracks what you're saying now. The
  engine owns the length (GPU keeps 20 s — large-v3-turbo handles code-switch),
  hot-read so a retune needs no restart. Default to be settled on real captured
  takes (#7), not synthetic translation-pairs.

### Doctrine
- **Suppress, never rewrite — and only what the decoder itself flags.** A
  confident *mishear* of real speech ("ta courte vie") is left to flash and let
  the final decode overwrite it: distinguishing it from a correct decode means
  judging meaning, which a wrong autocorrect makes worse than a visible mishear.
  Empirically, faster-whisper's internal thresholds + VAD already drop most
  *silence* junk upstream; the real value-add is the denylist for the
  high-confidence caption ghosts that sail through every confidence gate. Bias
  is asymmetric: err toward *showing* a rough partial over a blank bubble (the
  live preview is what the user praised).

## Sprint 16 — 2026-06-26 · On t'entend enfin (mic meter, calibré pour de vrai)

Live-testing the CPU bubble on the 4080 laptop, the waveform looked dead: even
speaking loudly the bars never passed ~10%. Forensics (pavucontrol + a mic
probe) showed why, and the fix is a calibration, not a rewrite.

### Fixed
- **Mic meter recalibrated to a quiet laptop mic** (`config.py`,
  `tests/test_audio_level.py`) — the amplitude mapping (floor 80 / full-scale
  3000) was set on the louder XPS22 desktop mic. This laptop's mic is ~10× quieter
  (ambient RMS ~8, normal speech ~80-100, loud ~140-250), so *normal speech sat
  under the 80 floor* and mapped to flat bars — a meter that looked frozen.
  Lowered: floor 80 → 50 (below normal speech, above ambient), full-scale
  3000 → 300 (near a loud peak). Validated live (« très très très calibré »).
  Level tests made calibration-relative so a future per-mic retune won't break
  them.

### Doctrine
- **Mic level constants are per-machine — measure the actual mic, don't inherit.**
  The `3000` full-scale was never wrong on the box it was tuned on; it was wrong
  *transplanted*. A meter calibrated above the new mic's speech floor is
  indistinguishable from a broken one. Forensics (real RMS numbers) before
  theory. The durable fix is auto-gain / a per-mic sensitivity setting (and the
  planned FFT spectrum self-normalises, sidestepping it) — see #2.
- **CPU quality is strategic, not a stopgap.** Mobile is a target, so "maximum
  quality on limited hardware" is the goal, not a fallback we tolerate until the
  GPU returns. Both the slow decode AND the colloquial-speech errors this session
  trace to the CPU qwen-0.6B model — but the answer isn't only "get the GPU
  back"; it's also audio pre-processing (#8) and text post-processing (#9) to
  squeeze the small model. Re-measure on GPU before blaming the model class (#7).

## Sprint 15 — 2026-06-26 · La couleur tient parole, le CPU prend la sienne

Two follow-ups from a real CPU-only run (GPU wedged by a suspend/resume, #124):
the bubble's colour broke its own promise, and the CPU bubble had no live text.

### Fixed
- **The bar colour holds its hue end to end** (`ui.py`, #color) — bars mean
  *which silicon* (green = GPU, blue = CPU), but the final "landed" flash was a
  fixed green, so a CPU take read blue → blue → **green** and looked like the GPU
  had woken up. Now the landed flash *brightens the live backend hue toward
  white*: green stays GPU, blue stays CPU, the hue is constant from first frame
  to last, and "landed" reads as brightness, not colour. (Supersedes Sprint 11's
  "brighter/whiter green" — that was the exact thing that misled.) `_bar_color()`
  is extracted so the contract is unit-tested headless (no GPU needed).

### Added
- **Live partials on CPU** (`engine.py`, `settings.py`, `settings_ui.py`, #127) —
  qwen can't stream (fresh process, ~0.4x realtime), so a CPU session used to get
  a waveform but no preview text. A separate small whisper on CPU
  (`CpuPartialsEngine`, default `base`, opt-out via *Réglages* « Aperçu en direct
  sur CPU ») now paints provisional text while you speak; the qwen final decode
  stays the source of truth and overwrites it. Cheap: faster-whisper is already a
  core dep and its CT2 CPU backend needs no CUDA, so only the small weights fetch
  on first use. The daemon's ~1 Hz partials loop self-paces (bounded window +
  elapsed-subtracted cadence), so a long window yields fewer partials, never a
  backlog; if the small model can't load, the bubble degrades to waveform-only.
  This closes the last GPU-or-nothing gap — partials now degrade GPU-or-CPU like
  every other feature.

## Sprint 14 — 2026-06-26 · Rejoue ta voix (dev take-capture)

The transliteration ablation (Sprint 13) proved a seed fix survives *synthetic*
TTS acoustics. To prove it survives *yours*, you need your real audio on tap — a
dev mode that stashes every take so it can be re-decoded across engines and seed
regimes. "Forensics before theory", now with a real-audio substrate.

### Added
- **Dev take-capture** (`takes.py`, `daemon.py`) — with `TUPARLES_DEV` set, every
  landed take's raw PCM is written to `takes/<id>.wav`, keyed to its history row,
  next to the DB. Off for everyone else.
- **`history.record()` returns the row id** so the capture can pair audio ↔
  transcript (backward-compatible; existing callers ignore it).
- **`scripts/replay_takes.py`** — re-decodes captured takes across seed regimes
  and reports WER **drift vs the stored transcript** (the real-audio sibling of
  `scripts/measure_seed_ablation.py`, which runs on TTS). Engine-swap is a
  one-line extension.

### Doctrine
- **Raw voice on disk is opt-in via an env var, never a UI toggle.** This is your
  unredacted voice (the stored transcript strips block-tier PII, #115; audio
  can't be). So the gate is `TUPARLES_DEV` — a setting you can leave ON by
  accident is the wrong shape for this. Local-only, and **self-pruning**: oldest
  takes are evicted past a byte budget (256 MB ≈ ~2 h) so a dev convenience can
  never silently fill a disk.

## Sprint 13 — 2026-06-25 · Translittération : on seede ce qu'on dit (forensics)

A forensic read of the day's history DB (last 10 takes) turned "grosses erreurs
de translittération" into a measured taxonomy: ~80% of the damage is technical
vocabulary with no decoder anchor — acronyms and names re-lexicalised into the
nearest ordinary word (DKIM → « des KIM », DMARC → « des marques », qwen →
« Quinn », CPU → « CPP », UI → « l'ueil », Postgres → « Postgre », the personal
domains nech.pl/plnech.fr → « Neck.tl »). The fix follows the metric (low FP,
low FN), not the gut. See
`docs/research/2026-06-25-transliteration-forensics.md`.

### Added
- **7 real-misfire cases in the code-switch corpus** (`tests/data/codeswitch/`)
  — DKIM/DMARC, PII/privacy, qwen/build/CPU, UI, Postgres, the personal domains,
  and an **identity gate** for the user's own name. `must_contain` measures
  recall (FN); `must_not_contain` measures the legit-word trap we must NOT emit
  (FP — « des marques », « Bill », « Quinn » are all real tokens). Each case's
  note records *why* it is bias-only or lexicon-safe.
- **`vocab.txt` seeded with infra acronyms + identity** (local, gitignored) —
  DKIM/DMARC/SPF/DNS/PII, Postgres, and `nech.pl`/`plnech.fr`/`Nech`/
  `Paul-Louis Nech`/username, ridden at the prompt *tail* so they survive
  Whisper's 224-token truncation. Zero-FP (advisory bias), immediate.

### Fixed
- **`Postgre → postgres`** in the lexicon (`lexicon.py`) — the lone offender
  safe to rewrite deterministically, because « Postgre » is a non-word that is
  *never* intended (`\bPostgre\b` leaves `Postgres`/`PostgreSQL` untouched).
- **Over-seeding hallucination** (`seed_prompt.py`) — the GPU ablation caught the
  production prompt (manual + ~26 codebase auto-seeds, 747 chars) scoring *worse*
  than manual-only and hallucinating letter-spelled garbage (`J.V.U.K.W.N…`):
  `ALL_CAPS`/`CamelCase` identifiers near the 224-token ceiling teach the decoder
  to spell. New `_PROMPT_CHAR_BUDGET` (400) trims auto-seeds (least-important
  first) to a hard cap well under the tail-keep; the curated manual glossary is
  never dropped. Production prompt 747 → 376 chars; FULL went from 20/58 (one
  hallucination) to 21/58 pass, now *beating* manual-only.

### Measured (GPU box, 58 WAVs = 29 cases × 2 cross-lingual voices)
Ran it, didn't argue it (`scripts/measure_seed_ablation.py`, OFF/CURATED/FULL
ablation): on the new target errors, seeding **nearly doubled recall, 29 → 57%,
with FP held at 0%**. Rescues incl. `qwen`, `CPU`, `Postgres`, and the one that
mattered — **`Paul-Louis Nech`** (baseline heard « Paul Wienek »). All-case
recall 52 → 59%, leaks 4 → 3. High recall, low FP — the goal, with a number.

### Doctrine
- **Bias raises recall for free; rewriting risks FP — so this whole error class
  is bias-only.** The acronym/name misfires (« des marques » = DMARC, « Bill »
  = build, « Quinn » = qwen, « CPP » = C++) collapse into *legitimate* words, so
  a post-decode rewrite would be a false positive. The decoder `initial_prompt`
  can only nudge, never insert — it's the zero-FP lever. The lexicon stays
  nearly empty by design; only true non-words earn a rule.
- **The 224-token budget is the real constraint.** "Seed 10k tech words" is
  physically impossible (and hallucination-prone). The lever isn't volume, it's
  *selection* of the ~30 best slots — next, TF-IDF over the history DB to rank
  them from what the user actually says.

## Sprint 12 — 2026-06-25 · Une bulle par écran (multi-monitor finish)

The two `bubble_screen` modes deferred at v0.2.0 (Sprint 11), now landed — so
the multi-monitor story is complete instead of half-told.

### Added
- **Mirror the bubble on every screen** (`ui.py`, `daemon.py`, `settings.py`,
  `settings_ui.py`) — a new `bubble_screen: "all"` lights one bubble per monitor
  at once. The daemon's face is now a `BubbleGroup` that fans every call
  (`start_recording`/`set_partial`/`show_final`/…) out to the bubbles active for
  the take; "all" simply makes the active set *every* screen. A `@Slot hide()`
  fans the Wayland paste-hide out too, so **every** mirror yields keyboard focus
  before the paste — else it would land in whichever bubble still held focus, not
  your window. Single-screen modes light exactly one bubble, so a one-monitor
  setup is byte-for-byte the old behaviour, reached through the group.
- **Follow the active window's screen** (`ui.py`, `settings.py`,
  `settings_ui.py`) — `bubble_screen: "focus"` puts the bubble where your text is
  about to land. On X11 it maps the focused window's centre to a screen; on
  native Wayland, where a client can't read the focused window's geometry, it
  **degrades to the cursor's screen** (a reliable "where I'm working" proxy)
  rather than silently doing nothing — *a setting that no-ops is worse than
  absent*. Documented as such in the picker hint.

### Changed
- **The bubble's screen resolution is one shared function** (`ui.py`
  `resolve_screen`/`resolve_screens`) — the single Bubble and the BubbleGroup
  both route through it, so pin / cursor / focus / mirror can never mean two
  different things. All four modes resolve **fresh each take**, so the mode (the
  mirror included) applies live, no restart.

### Infra
- **Release notes come from the CHANGELOG, not the commit list** (`release.yml`)
  — `release.yml` now extracts the top `## …` section (same rule as
  `whatsnew.latest_section`) and publishes it via `--notes-file`, falling back to
  `--generate-notes` if there's no section. Published releases now read like the
  curated documentary the team writes.

## Sprint 11 — 2026-06-25 · La bulle prend vie (Bubble UX & engine-status pass)

First real-world run on the XPS22 (Arch, Plasma 6 Wayland, RTX 2060) surfaced a
batch of bubble-legibility papercuts (see `SPEC.md`). This sprint makes the
bubble *tell you what's happening*.

### Changed
- **Perceptual mic meter** (`audio.py`, `config.py`, SPEC §2) — the waveform was
  a linear `rms / 8000` over the full int16 range, so quiet/mid speech mapped to
  near-flat bars. Now a light noise gate + speech-scaled normalize + perceptual
  gamma (`LEVEL_NOISE_FLOOR` / `LEVEL_FULL_SCALE` / `LEVEL_GAMMA`): silence rests
  flat, soft speech still clearly moves the bars. The bars jumping *is* the "I
  hear you" cue, so this is also the start-of-recording feedback.
- **Bars encode the engine: green = GPU, blue = CPU** (`ui.py`, `tray.py`,
  `engine.py`, `daemon.py`, SPEC §5) — recording **and** processing bars (bubble
  *and* tray glyph) now take an ambient colour from the live backend, via a
  `backend_source` pull that mirrors `level_source`. `ResilientEngine` exposes
  `active_backend` ("gpu"/"cpu"); the session-sticky fallback means it goes blue
  exactly when the GPU has truly given up. The final flash is a brighter/whiter
  green ("landed"), error stays red. **This changes the default look** (blue →
  green while recording on GPU) — deliberate.
- **Default view is now `full`** (`settings.py`, SPEC §4) — a dictation tool
  should show your whole take; a long take elided to ~5 words starved context.
  `minimal` stays the opt-in discreet one-line pill (tray · *Réglages*).
- **Processing animation is a sweeping pulse** (`ui.py`, SPEC §3) — the idle
  breathing wave read as "barely alive"; processing now sends a bright pulse
  scanning across the bars, visually distinct from idle and the final flash.

### Added
- **Role phrase packs** (`rolepacks.py`, `quickchat.py`, `cheatsheet.py`,
  `onboarding.py`, #90, EPIC #88) — the "Ton rôle" onboarding axis (#80) now
  *does* something: picking a role activates a curated, bilingual built-in
  quick-chat pack (eng / product / design / marketing / strategy) without
  hand-writing a `phrasepack.json`. `quickchat.active_phrases()` composes the
  personal pack FIRST, then the role pack, so personal triggers win on collision
  (a seed you extend, never a cage). Built-in triggers are deliberately *more*
  conservative than personal ones (distinctive multi-word / acronym, never a
  bare common word) since they arrive from one tap rather than a trigger you
  typed — `fullmatch` anchoring + a misfire corpus over the whole catalogue keep
  prose that merely contains a trigger as text. Activated macros are
  discoverable in `tuparles cheatsheet`, and the onboarding preview now shows a
  **real** expansion (« lgtm » → LGTM 🚀) instead of naming the role. Pure-CPU.
- **A tray that breathes** (`tray.py`, `settings.py`, `settings_ui.py`) — the
  menubar glyph is now alive: a calm shallow breath (+ gentle bob) at rest, a
  livelier phase-shifted undulation while recording, and a travelling pulse
  while decoding — all in the engine colour. One ~10 Hz timer drives it. SNI
  trays ship each frame over DBus, so it's a `tray_animation` setting (default
  on; off = static glyph) — applied **live** (the Réglages `accepted` signal
  starts/stops the breath, no restart).
- **Optional start tick** (`cue.py`, `settings.py`, `settings_ui.py`) — a soft
  synthesized cue the instant capture goes live, for those who want an audible
  "speak now" on top of the visual cues. Opt-in (default off — a quiet local
  tool shouldn't beep); no new deps (synthesized through `sounddevice`).
- **Bubble screen (multi-monitor)** (`ui.py`, `settings.py`, `settings_ui.py`) —
  a `bubble_screen` setting + Réglages picker: **pin to a chosen monitor**
  (default `primary` — deterministic, identical to before on a single screen),
  or **follow the mouse** (the old behaviour). A pinned monitor that's been
  unplugged degrades to primary, never crashing a take. Read fresh on each
  appearance, so it applies on the next dictation — no restart. (Follow-focused-
  window and mirror-on-all deferred: focus-screen isn't reliably queryable on
  native Wayland, and mirroring touches the Wayland paste-hide path.)

### Fixed
- **Wayland bubble positioning** (`daemon.py`, `ui.py`, README, SPEC §1) — native
  Wayland compositors ignore client `move()`/`xprop`, centring the frameless
  bubble. The daemon now renders via XWayland (`QT_QPA_PLATFORM=xcb`) on a
  Wayland session so self-placement and all-desktops stickiness work again, and
  degrades honestly if forced to native Wayland (`_make_sticky` no-ops off xcb;
  a startup note instead of pretending). Cross-machine version of the per-box
  infra workaround.

### Infra
- **UTF-8 file I/O — Windows CI fixed** (`quickchat.py`, `vocab.py`,
  `seed_prompt.py`, `whatsnew.py`, `settings.py`, `telemetry/introspect.py`) —
  every `read_text`/`write_text` now passes `encoding="utf-8"`. On Windows the
  locale default (cp1252) choked on UTF-8 content: the example phrasepack
  failed to parse (red Windows matrix), and a `CHANGELOG`/`vocab.txt` with
  accents would have too. The JSON paths were ASCII-safe but are made explicit
  for uniformity. Pre-existing, surfaced by the cross-OS matrix.
- **Reconciled the modern-ydotool delivery tests** (`tests/test_delivery.py`) —
  Sprint 9's ydotool ≥1.0 support (evdev `<keycode>:<state>` pairs) shipped
  without updating the paste-combo tests, which still pinned the daemon-less
  `ctrl+v` argv and didn't control `_YDOTOOL_MODERN` (so they passed/failed by
  whether `ydotoold` was installed on the box). Tests now pin the backend
  explicitly and `TestYdotoolArgv` covers both generations.

## Sprint 10 — 2026-06-24 · Ton style (personalized casing) + le GPU qui revient

### Added
- **Onboarding — no-Qt text view + Réglages toggle** (`cli.py`,
  `settings_ui.py`, `daemon.py`, #80) — the personalization core is now
  *reachable*: `tuparles onboarding` (`--replay` to re-run) walks the four axes
  as a numbered terminal prompt, each choice shown beside its **real** live
  preview; Entrée leaves a setting untouched, `q` keeps the rest. The daemon
  prints a one-line first-launch nudge (gated by `should_show()`, so it stops
  once configured). `casing_style` also gets its Réglages picker, sharing the
  onboarding card's exact labels so the two surfaces can't disagree. This is the
  graceful-degradation half of the onboarding pair (Qt-or-terminal); the
  animated Qt carousel is still to come — first-launch *auto-surfacing* awaits
  it, the CLI is the manual + headless path today.
- **« Comment Tu Parles ? » onboarding — core** (`onboarding.py`, #80, EPIC
  #55) — the personalization front door: a first-launch / post-update card that
  offers four perso axes, each with a conservative default — **Ton style**
  (casing #120), **Ton rôle** (role pack #90), **Tes langues**, **Ta vue** — and
  becomes the first UI that writes `casing_style`, waking the re-case engine.
  Pure testable core (this commit): trigger logic (`axes(force=)`, tracked by
  `onboarding_done` + `onboarding_axes_seen` so a release that adds an axis
  re-surfaces only the new one; manual replay forces all), a `preview(key,
  value)` that runs the **real** engine so the card can't show a style the
  pipeline wouldn't produce, and `apply_choices` writing each choice to
  settings. Two views ride on top (next): the sleek animated Qt carousel + a
  no-Qt `tuparles onboarding` text fallback — graceful degradation made literal,
  same core/view split as the cheat-sheet (#83). Design note in `docs/research/`.
- **Voice-caps — region all-caps** (`syntax_features/caps.py`, #59, EPIC #53) —
  the second spoken-syntax family after quotes. Wrap a passage to SHOUT between
  a paired open/close, bilingual: "tout en majuscules … fin des majuscules" /
  "all caps … end caps"; the span is upper-cased and the trigger words removed.
  Safety is structural — **require-close**: a region fires only as a complete
  open…close pair, so a lone "tout en majuscules" stays literal text
  (deliberately more conservative than quotes' auto-close — an unclosed caps
  region would shout the rest of the take). A mode-switch close synonym
  ("en minuscules" / "minuscule" / "lowercase") ends the shout, safe because
  require-close ignores it without a preceding open. The misfire corpus
  ("je l'ai écrit en majuscule", …) is the load-bearing test. Composes with the
  #120 `lower` style for free — an all-caps run reads as an acronym to the
  guard. Deferred to a follow-up: next-word capitalize + the general dual-mode
  mode-switch engine (needs a mode register + the quasimode #62 for a safe
  next-word trigger).
- **Re-case engine — personalized-casing core** (`casing.py`, #120, EPIC #119)
  — *descriptive* casing: re-case the final text to the style you actually
  write in. `recase(text, style, *, protect=)` with styles `preserve` (default,
  pure identity — ships dark), `lower` (lowkey all-lowercase), `sentence`
  (Capitalize sentence starts, never down-case the middle so proper nouns
  survive), `upper`. Conservative model-free guards never re-case non-prose:
  URLs / emails / @handles, identifiers (camelCase, snake_case, digit-bearing),
  and ALL-CAPS acronyms. A `protect` predicate is the seam where smart
  proper-noun detection (#122) and the gazetteer (#116) plug in later. Wired as
  the **last** `pipeline.postprocess` stage; a new `casing_style` setting
  (default `preserve`) keeps it an identity until you opt in. "It's a setting."
  - **Honest limit until #122:** `lower` also lowercases proper nouns
    ("paris") and plural acronyms ("apis") — `str.isupper()` is False on
    "APIs". That's the lowkey aesthetic, opt-in, documented; not a bug.
  - Doctrine in action: sentence-case treats a terminator *behind a closing
    quote* (`he said "go."`) as **not** a boundary, so we never capitalize the
    next word on an ambiguous quote-internal period. A missed cosmetic beats a
    wrong rewrite — *when in doubt, it's text.*

### Infra
- **GPU CUDA stack repaired** (#124, Option 1 — venv patch) — `ctranslate2
  4.8.0` hard-imports `torch 2.1.0`, whose loader demanded the full CUDA
  **12.1** lib convoy while the installed `nvidia-cu12` stack was **12.9**
  (pulled by faster-whisper). Installed the missing 12.9 wheels (cupti +
  cufft / curand / cusolver / cusparse / nccl / nvtx / nvjitlink), leaning on
  CUDA minor-version forward-compat, so torch → ctranslate2 import again. These
  wheels are **off `poetry.lock`**; the durable fix (align torch to the
  ctranslate2 CUDA gen in `pyproject`, then re-lock) is tracked as **#124**.
  GPU verification deferred — laptop on battery (econ power mode).

## Sprint 9 — 2026-06-24 · Le pare-feu se branche (PII firewall, from core to live)

### Infra
- **Distro-portable install** (`install.sh`, `scripts/setup_wayland.sh`) — the
  installer no longer assumes apt. A small package-manager layer
  (`detect_pm` / `map_pkg` / `pkg_install`) maps the logical deps to apt /
  pacman / dnf / zypper names (`libopenblas-dev`↔`openblas`↔`openblas-devel`,
  `libportaudio2`↔`portaudio`), so Arch/Fedora/openSUSE install with the same
  one-liner. Desktop messaging is no longer GNOME-specific.
- **Modern ydotool support (Wayland delivery beyond Ubuntu)** (`delivery.py`,
  `scripts/setup_wayland.sh`) — Ubuntu ships ydotool 0.1.8 (daemon-less, `key`
  takes a `ctrl+v` chord string); ydotool ≥1.0 (Arch/Fedora) needs a running
  `ydotoold` and `key` takes `<keycode>:<state>` evdev pairs instead. Delivery
  now detects which CLI is present (via the `ydotoold` binary) and emits the
  right argv; `setup_wayland.sh` installs a `ydotoold` **user service** +
  `YDOTOOL_SOCKET` env (environment.d) when modern, and only cleans up the
  obsolete unit on the daemon-less path. Non-GNOME Wayland (KDE, etc.) now
  prints what it does for terminal paste instead of silently degrading.

### Added
- **PII deterministic core** (`src/tuparles/privacy/`, #103) — the
  high-assurance, no-model / no-torch layer: known secret prefixes + Shannon
  entropy, checksum-validated structured PII (`python-stdnum`: IBAN / FR NIR /
  Luhn), a Scunthorpe-safe normalized denylist, a frequency floor for
  aggregates, and a `scan` / `redact` orchestrator. Two safety tiers: `block`
  (precise enough to redact) vs `alert` (surfaced, never auto-redacted).
- **PII firewall wired into the live paths** (`privacy_policy.py`, #115) — the
  core now runs over the utterance persist path and the analytics tag cloud.
  Dictation is still pasted **verbatim**; only the *stored* transcript is
  minimized (block-tier `<KIND>` placeholders before `history.db`). A
  `Réglages › Confidentialité` toggle (`pii_redact_history`, default on) and a
  configurable analytics frequency floor (`pii_analytics_min_count`).
- **PII eval corpus + leakage harness** (`tests/data/pii/corpus.json`,
  `tests/test_pii_eval.py`, `privacy/eval.py`, #104) — 27 FR+EN red-team cases
  scoring two asymmetric metrics: LEAKAGE (a planted secret that survived — must
  be zero) and OVER-REDACTION (clean text wrongly masked — must be zero too,
  since the detectors are deterministic). Pure text, runs in the normal suite,
  so a privacy regression breaks CI. First run: **0% leakage, 0% over-redaction**.
- **Réglages › Pare-feu PII — denylist editor** (`PrivacyDialog`, #107) — a
  two-tier term editor (block = masked from the stored record, alert = surfaced
  but never auto-redacted) plus the analytics anonymity-floor knob. Pure
  `parse_terms` helper (one term per line, de-duped) is unit-tested; an
  offscreen-Qt round-trip pins that the dialog writes exactly the keys the
  engine reads. Operator profiles / faker / cloud-egress arrive with #105.

### Fixed
- **Card detector demoted Luhn from sole authority** (#104) — bare Luhn passes
  ~1-in-10 random digit strings, so a 15-digit order number was being masked as
  an Amex. Block-tier now also requires a real network IIN prefix + a length
  that network issues (Visa / MC / Amex / Discover / UnionPay / Diners / JCB).
  The eval caught this on its first run — exactly why "measure before you trust".

### Added
- **What's-new on update — core + `tuparles whatsnew`** (`whatsnew.py`, #82) —
  detects when the installed version differs from the last one you were shown and
  surfaces the top CHANGELOG section once; `tuparles whatsnew` shows it on demand.
  Pure + injectable (version + changelog text), reuses #86's version sense. The
  tray/dialog card that auto-pops on first launch after an update is a thin Qt
  follow-up on this core.
- **Dict-seed bias feed** (`seed_prompt.py`, #68) — Whisper's `initial_prompt`
  now folds the codebase's top dict-seed terms (from the cached EDA) in with your
  manual glossary, so the decoder spells `getFacetValues` right. Advisory only
  (it nudges, never forces), so it's on by default behind `dictseed_bias`. Manual
  glossary rides at the tail so it survives Whisper's 224-token tail-keep and wins
  dedup. The risky *post-correct* half is deferred to #69 — a transcript rewrite
  earns its place against the FP/FN harness first (a wrong autocorrect is worse
  than a visible mishear). Effectiveness will be measured there; this ships the
  safe, tested mechanism.
- **`tuparles report` — prefilled bug-report URL** (`bugreport.py`, #87) — builds
  a `github.com/PLNech/TuParles/issues/new?title=…&body=…` link with an
  auto-gathered environment block (version / Python / OS / Wayland-vs-X11) and
  opens it in the browser. No token, no API, no account data sent — a public repo
  can't ship a usable token, so the URL path is the honest answer (first piece of
  onboarding epic #55).
- **`tuparles update` — update checker** (`update_check.py`, #86) — queries the
  public GitHub Releases API (no token) and compares against the installed
  version. **Opt-in** (`update_check_enabled`, default off — a network call
  reveals you run the tool, so local-first means you choose); `tuparles update`
  always works manually. Pure version compare + injectable fetch (tests never
  touch the network); every failure path returns `None` so a dead check can't
  cost a launch.

### Added
- **Cheat-sheet core + `tuparles cheatsheet [query]`** (`cheatsheet.py`, #83) —
  one searchable, bilingual reference of every voice command and syntax phrase,
  **derived from the live grammar**: `commands.vocabulary()` (a new public view
  of the #41 meta-language), `punctuation.SPOKEN_TO_SYMBOL`, and a new
  `syntax.catalogue()` over the registered families — each family now carries
  its own `summary`/`triggers` help, co-located with its regex so it can't
  drift. Search is accent- and case-insensitive. A `humanize()` turns the
  punctuation regexes into readable phrases, guarded by a test that fails if a
  pattern grows a construct it can't render. Pure core; the tray/settings panel
  is a thin render over `entries()` (onboarding epic #55, blocks #85). The sheet
  also surfaces your own quick-chat macros (#89) once you have a pack, so a
  macro you defined is discoverable, not a secret you must remember.
- **Quick-chat / voice macros — engine + pack format** (`quickchat.py`, #89) —
  a SHORT spoken trigger expands to a curated text (CS-radio "enemy spotted"
  meets Dragon auto-texts). Pure anchored engine: a trigger fires only on a
  whole-take `fullmatch` (never a substring inside prose — *when in doubt it's
  text*, same doctrine as #41), with `<name>` template slots filled from what
  you say. The pack is a hand-editable `~/.config/tuparles/phrasepack.json`
  (`phrasepack.example.json` to copy), re-read every take like vocab. Safe-on
  (`quickchat_enabled`): an empty pack is a no-op, so it can't fire until you
  write a macro. Wired into the daemon between the command and delivery stages;
  the expansion is delivered and recorded like any dictation. Role packs (#90)
  and richer activation (#91) build on this core. 23 tests incl. a misfire corpus.
- **Spoken help — "que peux-tu faire ?"** (#85) — a new `help` voice command
  (a structurally-safe whitelist of distinctive multi-word phrases, FR+EN; never
  bare "aide"/"help", which collide with prose) pops the cheat-sheet as a
  fire-and-forget desktop notification. Shares the one `cheatsheet.as_text()`
  renderer with the CLI (a `brief` mode sized for the toast), so voice, terminal
  and the future panel can't show different help. No `notify-send` → the
  confirmation toast points at `tuparles cheatsheet`.

### Infra
- **CI off Node 20** (#43) — `actions/checkout@v4→v5` and `setup-python@v5→v6`
  (Node 24). GitHub force-deprecates Node 20 on runners in June 2026 and removes
  it 2026-09-16; this clears the warning spam and future-proofs the cross-OS matrix.
- **CI lint pinned to poetry.lock** (#43) — `ruff==0.9.10` + `mypy==2.1.0`
  installed explicitly, and `python-stdnum` added to the runner deps. An unpinned
  `ruff` had auto-bumped on the runner and failed the matrix on new `UP` rules in
  untouched files; CI lint now can't silently drift from local.
- **CI green again** (#43) — `main`'s matrix had been red for many commits
  (predating this sprint), each failing step masking the next. Full repair:
  (1) ran `ruff format` over the tree (a separate gate from `ruff check`);
  (2) `hotkey.py` `cast(Any, key.fileobj)` so the evdev-less type-check is
  consistent (evdev is an optional Linux dep absent on runners);
  (3) `mypy` `platform = "linux"` — the app is Unix-only (fcntl/evdev/X11), so
  type-checking for the deploy target stops Windows/macos cells flagging
  `fcntl.flock`; (4) `pytest.importorskip("PySide6")` guards on the Qt-touching
  tests (dashboard HTML, offscreen Controller, PrivacyDialog) so they skip on the
  Qt-less runners instead of erroring. The cross-OS matrix exists for the
  pure-python *runtime*; type/Qt concerns are pinned to the real target.

### Forensics
- **Mined a real greenfield take into the code-switch corpus** (#83 side-quest,
  `docs/research/2026-06-24-real-take-error-taxonomy.md`) — a ~250-word French
  monologue dictated with *zero* context (a `claude.ai/new` field) gave us the
  bare decoder's raw behaviour. Four cases added: the misfire `des APIs` →
  `des épiailles` (English plural acronym, the `-z` dissolving into `-ailles`)
  plus three survivals pinned against regression (`highscore`, `replayable`,
  `self-contained`). Corpus now 22 cases; await WAV-regen + GPU run (#52).
- **Corpus integrity guard** (`tests/test_codeswitch_corpus.py`) — pure, no-GPU.
  Found that the scorer's `normalize()` collapses hyphen/apostrophe to space, so
  a `must_contain` + `must_not_contain` reducing to the same tokens makes a case
  *impossible to pass* (`self-contained` vs `self contained`). The guard asserts
  that, plus unique ids and that every reference `text` passes its own gate.
- **Seeded the dict-seed prior** (#116, #117) — the proper-noun casualties
  (`Charlottesville`→`Charles de ville`, `Tombouctou`→`Tombout`) and the
  `épiailles` misfire argue for a **personal + register frequency prior**:
  bake an offline freq-ratio table (`wordfreq`/Lexique, frequencies-are-facts),
  TF-IDF the "uniquely yours" terms, RRF-fuse cold/warm/hot signals into
  Whisper's 224-token tail. The #54 EPIC's missing half, written up for #42.

### Doctrine
- **Minimize before persist, never before deliver.** The paste hot-path is
  sacred — you always get exactly what you said. The firewall shapes only what
  we keep, so a dictated secret lands in the focused app but never on disk.
- **Precision earns the right to redact.** Only checksum-validated / known-prefix
  spans carry block authority (~zero false positives); the statistical net
  (names, topics) stays alert-only until #106. Glue (settings-aware) lives one
  level out of the pure, rentable `privacy/` core.

### Research
- **The personal + register prior** (`docs/research/2026-06-24-real-take-error-taxonomy.md`)
  — mined a real greenfield take; the proper-noun casualties + the `épiailles`
  misfire argue for a frequency prior (`wordfreq` IDF + TF-IDF "uniquely yours"
  + RRF over cold/warm/hot signals into Whisper's 224-token tail). The #54 EPIC's
  missing half (#116 entity-aware seeding, #117 register prior).
- **Granola, in and out** (`docs/research/2026-06-24-granola-bridge-in-out.md`,
  #118) — the team records meetings in Granola, so: IN = mine that corpus (local
  cache, offline) as a dict-seed context source (the team's meetings teach
  TuParles its vocab); OUT = roundtable mode (#108/#38) as the sovereign
  note-taker (Granola's API is read-only — we export, not write-back). Plus 3
  links + tips + a privacy flag shared with the team.
- **Personalized casing — a new moat** (#119 epic → #120–123) — match the user's
  natural capitalization fingerprint (lowkey-lowercase / Proper / code-casual)
  instead of Whisper's one formal house style. Signal stack: explicit setting →
  current-box register (hot) → history profile (warm) → app-class → per-language.
  Safety crux: re-casing is a rewrite, so smart-lowercase must preserve proper
  nouns/acronyms (converges on #116's entity detection); default = preserve.

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
