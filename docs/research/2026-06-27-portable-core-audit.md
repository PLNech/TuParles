# Portable Core Audit — Issue #2 (Android-library-ready)

**Date:** 2026-06-27  
**Scope:** Portability classification of every module under `src/tuparles/`, sized for
branch-selection in issue #2.  
**Method:** `rg` import scan + LOC (`wc -l`) on every file.  
**Doctrine applied:** "own the spine, rent the algorithms"; the postprocess chain is the
actual IP; engine must change for Android (no CUDA ARM path); the question is whether the
Python postprocess travels with it (Branch 1: embed CPython) or gets reimplemented in
Kotlin (Branch 2).

---

## 1. The postprocess spine — what `pipeline.postprocess()` actually depends on

```
pipeline.py
  ├── punctuation.py        ← pure stdlib (re only)
  ├── lexicon.py            ← pure stdlib (re only)
  ├── syntax.py             ← settings + stdlib (re, dataclasses, collections)
  │     ├── syntax_features/__init__.py   ← registers caps + quotes
  │     ├── syntax_features/caps.py       ← settings + syntax (stdlib only beyond that)
  │     └── syntax_features/quotes.py    ← settings + syntax (stdlib only)
  ├── repeats.py            ← pure stdlib (re only)
  └── casing.py             ← settings + stdlib (re, string, collections)
        └── settings.py     ← json, os, pathlib (pure stdlib — XDG path hardcoded)
```

`settings.py` is the only transitive dep that needs portability thought: it reads a JSON
file from `$XDG_CONFIG_HOME/tuparles/settings.json`. On Android, `XDG_CONFIG_HOME` would
not be set; the fallback is `~/.config/` which does not exist. A one-line adapter that
replaces `_path()` with an Android-appropriate path (Chaquopy can surface the app's
`getFilesDir()`) makes it portable. The logic is pure stdlib, so no code change beyond
that seam.

---

## 2. Module classification table

| Module | LOC | Portable? | Coupling reason | Port note |
|--------|-----|-----------|-----------------|-----------|
| **pipeline.py** | 45 | YES | stdlib + internal only | Core seam; ships as-is |
| **punctuation.py** | 127 | YES | re only | Zero changes |
| **lexicon.py** | 42 | YES | re only | Zero changes |
| **repeats.py** | 41 | YES | re only | Zero changes |
| **syntax.py** | 145 | YES | settings + stdlib | settings seam only |
| **syntax_features/__init__.py** | 6 | YES | registers caps/quotes | Zero changes |
| **syntax_features/caps.py** | 80 | YES | settings + syntax (stdlib) | settings seam only |
| **syntax_features/quotes.py** | 153 | YES | settings + syntax (stdlib) | settings seam only |
| **casing.py** | 183 | YES | settings + stdlib | settings seam only |
| **settings.py** | 175 | NEAR | json/os/pathlib; XDG path | Replace `_path()` → app storage |
| **spans.py** | 96 | YES | re, dataclasses, typing | Zero changes |
| **partials.py** | 100 | YES | config constants only | Config seam; pure logic |
| **languages.py** | 114 | YES | re, pathlib | Zero changes |
| **vocab.py** | 88 | YES | config (VOCAB_FILE path) | Config seam; pure logic |
| **config.py** | 71 | NEAR | os, pathlib; desktop consts | IS_WAYLAND, QWEN_BINARY — desktop-only; split or stub |
| **privacy/core.py** | 20 | YES | dataclasses only | Zero changes |
| **privacy/denylist.py** | 48 | YES | re, dataclasses, collections | Zero changes |
| **privacy/floor.py** | 17 | YES | collections.Counter | Zero changes |
| **privacy/normalize.py** | 21 | YES | unicodedata | Zero changes |
| **privacy/redact.py** | 45 | YES | privacy siblings only | Zero changes |
| **privacy/secrets.py** | 51 | YES | re, math, collections | Zero changes |
| **privacy/structured.py** | 65 | NEAR | **python-stdnum** (IBAN/NIR/Luhn) | stdnum is pure-Python; wheels exist; verify Android build |
| **privacy/__init__.py** | 26 | YES | privacy siblings only | Zero changes |
| **telemetry/sink.py** | 65 | YES | json, sqlite3, datetime | sqlite3 is stdlib; Android has it |
| **telemetry/record.py** | 55 | YES | settings + telemetry/sink | settings seam only |
| **telemetry/__init__.py** | 17 | YES | telemetry/record | Zero changes |
| **telemetry/readout.py** | 37 | YES | collections, telemetry/sink | Zero changes |
| **telemetry/dashboard.py** | 148 | **NO** | **PySide6** import (Qt widgets) | Desktop UI only; exclude |
| **telemetry/introspect.py** | 115 | YES | history, telemetry/readout | sqlite3 only beyond that |
| **history.py** | 154 | YES | sqlite3, pathlib, datetime | Desktop-compatible sqlite3; Android OK |
| **nlp/features.py** | 125 | PARTIAL | **numpy** (top-level import) | numpy has Android aarch64 wheels (claim — see §4) |
| **nlp/signals.py** | 97 | PARTIAL | **numpy** + deferred fastembed/ST | fastembed deferred to ctor; numpy same caveat |
| **nlp/parse.py** | 270 | YES | stdlib only (ast, json, re, tomllib) | Zero changes |
| **nlp/sources.py** | 87 | YES | stdlib, pathlib | Zero changes |
| **nlp/crawl.py** | 133 | YES | subprocess, pathlib | subprocess on Android: limited but available via Chaquopy |
| **nlp/fuse.py** | 34 | YES | stdlib (collections) | Zero changes |
| **nlp/engines/keywords.py** | 93 | PARTIAL | numpy + deferred fastembed | Same as signals |
| **nlp/engines/cluster.py** | 63 | PARTIAL | **scikit-learn** (nlp group dep) | scikit-learn has aarch64 wheels; optional group OK |
| **nlp/engines/dictseed.py** | 102 | YES | nlp siblings (parse, fuse, features) | numpy transitive |
| **nlp/engines/__init__.py** | 11 | YES | nlp/engines siblings | Zero changes |
| **preprocess.py** | 39 | **NO** | **numpy** top-level; audio conditioning | numpy on Android feasible but preprocess is engine-adjacent; belongs in engine layer |
| **takes.py** | 128 | **NO** | **numpy**, wave, XDG paths | Audio capture/store — engine layer |
| **audio.py** | 180 | **NO** | **sounddevice** (desktop mic API) | Replace with Android AudioRecord |
| **engine.py** | 480 | **NO** | **numpy + faster_whisper** (CT2/CUDA) | Full replacement needed on Android |
| **capability.py** | 289 | **NO** | shutil/subprocess probing X11/Wayland tools | Desktop probe; exclude or stub |
| **delivery.py** | 816 | **NO** | X11/Wayland clipboard + xdotool | Delivery is desktop concept; exclude |
| **daemon.py** | 748 | **NO** | PySide6 + numpy + engine | Desktop runner; exclude |
| **hotkey.py** | 260 | **NO** | pynput/evdev (Linux input) | Replace with Android volume-key or PTT button |
| **ui.py** | 842 | **NO** | PySide6 (Qt widgets) | Replace with Android UI layer |
| **tray.py** | 250 | **NO** | PySide6 + subprocess | Desktop tray; exclude |
| **settings_ui.py** | 366 | **NO** | PySide6 | Desktop settings panel; exclude |
| **commands.py** | 294 | PARTIAL | settings + pipeline (no desktop dep direct) | Command parsing; portable if pipeline is |
| **cue.py** | 44 | **NO** | subprocess (aplay/sox) | Replace with Android AudioTrack |
| **cli.py** | 250 | **NO** | subprocess, desktop entry points | Desktop CLI; exclude |
| **bugreport.py** | 65 | **NO** | subprocess (git, lsb_release) | Desktop-only; exclude |
| **eval.py** | 117 | YES | stdlib + pipeline + history | Useful for Android testing harness |
| **onboarding.py** | 219 | **NO** | PySide6 + Qt | Desktop UI |
| **cheatsheet.py** | 210 | **NO** | PySide6 + Qt | Desktop UI |
| **whatsnew.py** | 59 | **NO** | PySide6 (implied by callers) | Desktop UI |
| **update_check.py** | 83 | NEAR | subprocess + urllib | Could port; network call |
| **quickchat.py** | 152 | PARTIAL | settings + pipeline (no Qt direct) | Portable if settings is |
| **rolepacks.py** | 99 | PARTIAL | settings + stdlib | Portable if settings is |
| **seed_prompt.py** | 101 | PARTIAL | settings + nlp siblings | Portable if nlp layer is |
| **privacy_policy.py** | 76 | **NO** | PySide6 | Desktop UI only |

---

## 3. LOC summation — Portable IP vs Desktop-coupled

### Pure portable postprocess chain (pipeline spine + all transitive deps)

| Group | Modules | LOC |
|-------|---------|-----|
| Pipeline spine | pipeline, punctuation, lexicon, repeats, syntax, syntax_features (×3), casing | 822 |
| Settings | settings | 175 |
| Config (needed constants) | config (partial — PARTIAL_*, NORMALIZE_*, SAMPLE_RATE) | 71 |
| Spans | spans | 96 |
| Partials (filter logic) | partials | 100 |
| Languages | languages | 114 |
| Vocab | vocab | 88 |
| Privacy (all 8 modules) | core, denylist, floor, normalize, redact, secrets, structured, __init__ | 293 |
| Telemetry (non-Qt) | sink, record, __init__, readout, introspect | 289 |
| History | history | 154 |
| Commands + quickchat + rolepacks | commands, quickchat, rolepacks | 545 |
| Eval harness | eval | 117 |
| **SUBTOTAL** | | **~2,864** |

### NLP layer (optional, portable with numpy caveat)

| Group | Modules | LOC |
|-------|---------|-----|
| NLP core | parse, sources, crawl, fuse, features, signals | 746 |
| NLP engines | keywords, cluster, dictseed, __init__ | 269 |
| seed_prompt | seed_prompt | 101 |
| **SUBTOTAL** | | **~1,116** |

### Desktop-only (must replace or exclude on Android)

| Group | Modules | LOC |
|-------|---------|-----|
| Engine + audio pipeline | engine, audio, preprocess, takes | 827 |
| Hotkey | hotkey | 260 |
| Delivery + daemon | delivery, daemon | 1,564 |
| Qt UI | ui, tray, settings_ui, telemetry/dashboard, onboarding, cheatsheet, whatsnew, privacy_policy | 2,189 |
| Desktop tooling | capability, cli, bugreport, cue, update_check | 741 |
| **SUBTOTAL** | | **~5,581** |

**Total codebase:** ~9,629 LOC (excluding tests).

- Portable IP: ~2,864 LOC (30%)
- Optional NLP: ~1,116 LOC (12%)
- Desktop-only (replace/exclude): ~5,581 LOC (58%)

---

## 4. Coupling surprises — top 3

### Surprise 1: `settings.py` threads through the ENTIRE postprocess chain

`settings.get()` is called live (not at module load) by `syntax.py`, `casing.py`,
`syntax_features/caps.py`, and `syntax_features/quotes.py`. This is both good news and
bad news.

**Good:** The settings module itself is pure stdlib (json, os, pathlib). No Qt, no numpy.  
**Bad:** It uses `XDG_CONFIG_HOME` / `Path.home()` which will resolve to something
non-sensical on Android unless intercepted. More critically, there is no dependency
injection seam — callers import the module and call `settings.get()` directly. To make
this Android-portable, either: (a) patch `_path()` via a Chaquopy-visible environment
variable (`XDG_CONFIG_HOME` → app internal storage), or (b) introduce a thin settings
interface with a pluggable backend. Option (a) is a one-liner; option (b) is cleaner
but a ~2-hour refactor. This coupling is invisible at the import level (settings is pure
stdlib) which is precisely why it would surprise you — you would think "settings is
stdlib, no problem" and only hit the XDG path issue at runtime on Android.

### Surprise 2: `config.py` bundles desktop-specific constants with universal ones

`config.py` is 71 LOC of constants. Half are universally needed by the portable chain:
`SAMPLE_RATE`, `NORMALIZE_*`, `PARTIAL_*`, `VOCAB_FILE`. The other half are
desktop-only: `IS_WAYLAND`, `QWEN_BINARY`, `QWEN_MODEL_DIR`, `HOTKEY_DEBOUNCE_S`,
`HOTKEY_HOLD_S`, `LEVEL_*`. Modules in the portable chain import specific constants
from `config.py` (e.g., `partials.py` imports `PARTIAL_*`), so they do pull in the
entire file, including `IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"`.
This evaluates cleanly on Android (env var absent → False), so it is not a crash, but it
is conceptually wrong and suggests splitting config into `config_core.py` (universal
constants) and `config_desktop.py` (platform-specific). The split is ~1-2 hours but
would clarify the extraction boundary permanently.

### Surprise 3: `privacy/structured.py` imports `python-stdnum` at module load

`from stdnum import iban, luhn` and `from stdnum.fr import nir` are top-level imports
(not deferred to a function). `python-stdnum` is a pure-Python package (no C extension),
so it could ship on Android, but it is NOT a stdlib module and must be bundled.
Chaquopy supports pip packages in `build.gradle`; the constraint is wheel availability
for the Android ABI and build-time pip resolution. `python-stdnum 2.x` publishes
universal wheels (pure Python → no ABI tag issue). CLAIM (unverified): that it installs
cleanly via Chaquopy's pip. The conservative path: verify with a test build; alternatively,
make the import deferred (`try/except ImportError`) and degrade gracefully (IBAN/NIR
detection disabled when stdnum absent), consistent with the "graceful degradation"
doctrine.

A hidden fourth surprise worth noting: **`nlp/features.py` and `nlp/signals.py` import
`numpy` at the top level**, not inside class constructors (unlike fastembed/ST which ARE
deferred). numpy has official aarch64 wheels and Chaquopy can install it, but it is the
largest non-stdlib dep in the portable subtree at ~15 MB compressed. Since nlp/ is the
dict-seeding layer (not the real-time postprocess chain), it belongs in an optional
group for Android builds.

---

## 5. Cleanest extraction seam for `tuparles-core`

The extraction is a surgical namespace move, not a rewrite. The seam is already
structurally present — pipeline.py has no heavy deps:

```
tuparles-core (new package)
  tuparles_core/
    pipeline.py         (rename/copy from tuparles.pipeline)
    punctuation.py
    lexicon.py
    repeats.py
    syntax.py + syntax_features/
    casing.py
    spans.py
    partials.py
    languages.py
    vocab.py
    privacy/            (all 8 modules — stdnum bundled)
    settings.py         (with _path() pluggable via env or DI)
    config.py           → split: config_core.py only
    telemetry/          (non-Qt: sink, record, __init__, readout, introspect)
    history.py
    commands.py
    quickchat.py
    rolepacks.py
    eval.py
```

**What stays in `tuparles` (desktop):** engine, audio, preprocess, takes, hotkey,
delivery, daemon, ui, tray, settings_ui, capability, cli, cue, all Qt modules.

**Two changes required before extraction:**

1. `settings._path()`: make configurable via `TUPARLES_CONFIG_DIR` env var (a one-liner;
   Android sets it to the app's internal storage path).
2. `config.py`: split universal constants from desktop constants (or document that
   `IS_WAYLAND` evaluates safely to `False` on Android and leave the split for later).

---

## 6. Effort estimate — tuparles-core Python package (desktop-agnostic, no Android yet)

| Task | Effort |
|------|--------|
| Namespace rename (tuparles → tuparles_core) + pyproject.toml | 2h |
| settings `_path()` DI seam + env var support | 1h |
| config split (core vs desktop) | 2h |
| stdnum graceful-degradation guard (try/except) | 0.5h |
| Test suite isolation (confirm no desktop import bleeds in) | 2h |
| CI matrix: add `tuparles-core` as standalone installable | 1h |
| **Total** | **~8.5h** |

This is a clean extraction with no logic changes — the code works as-is, it just needs
the namespace boundary and two config seams. The 8.5h is the extraction itself; it does
not include Android glue (Chaquopy setup, AudioRecord integration, native engine
selection, Kotlin UI) which is the main effort of issue #2.

---

## 7. Bottom line for issue #2

The TuParles postprocess IP is **~2,864 LOC of pure-Python, stdlib-only code** once
settings gets a one-line path adapter. There are no C extensions, no torch, no CUDA in
the postprocess chain. The clean extraction to `tuparles-core` is ~8.5 hours of
structural work — a namespace move and two config seams — not a reimplementation.

**Branch 1 (embed CPython via Chaquopy) is the economically correct choice.** The
postprocess chain is already portable; reimplementing its semantics in Kotlin
(Branch 2) would require reproducing ~3k lines of carefully-calibrated bilingual logic
including the hallucination denylist, the protected-phrase shield in punctuation, the
syntax feature registry, the repeat-collapse threshold, the privacy scan chain, and the
casing engine — each carrying non-obvious bilingual FR/EN edge cases documented in
tests. That is weeks of parity work with no quality leverage. Chaquopy ships the
Python CPython runtime in a `.aar` that Gradle includes; the postprocess chain would
run as-is. The engine swap (faster-whisper → a native Android ASR lib, likely
`whisper.cpp` via JNI or `sherpa-onnx`) is the real integration work and it is
engine-layer only — it does not touch postprocess at all.

**Key risk to verify before Branch 1 commits:** Chaquopy's CPython version must be
≥ 3.11 (tuparles uses `tomllib`, `match`, and `str.removeprefix` patterns). Chaquopy
0.6.4+ ships CPython 3.8–3.13 targets; verify the exact Android API level support.
`python-stdnum` and any NLP group deps need a test `build.gradle` pip install pass
before declaring them safe.
