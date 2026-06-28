# Four forks: UI, the core/frontend split, the whisper.cpp boundary, and the order

*2026-06-28. A planning session asked: how do we move the needle on the
laptop + server + Android implementations at once? Can the existing research feed
ergonomic choices of engine and install management? Is Qt still the right UI, or is
webview/SOTA the move? And what are `TuParles.app` vs `tuparles-service` vs
`tuparles-server` vs `tuparles-android` — how do they share structure/config/UX?*

*This note records the decisions reached (with the why), so the next session — or the
eventual blog (#42) — reconstructs them without the chat. No code shipped beyond the
import-boundary gate; this is the design record. Built on
[`2026-06-27-portable-core-audit.md`](2026-06-27-portable-core-audit.md) and
[`2026-06-28-cpu-engine-gradient-and-stt-api.md`](2026-06-28-cpu-engine-gradient-and-stt-api.md).*

## 0. The terrain that reframes everything (verify on your own box first)

Before any UI choice: the hard parts of a push-to-talk HUD are **Wayland protocol
problems**, not toolkit problems. They hit *every* framework equally and already live in
our Python/compositor layer, so they are **not** a UI-framework differentiator:

- **Global hotkey while unfocused** is forbidden in raw Wayland by design. Sanctioned
  path = the `org.freedesktop.portal.GlobalShortcuts` XDG portal (KDE has it; **GNOME 48
  shipped it, March 2025**; wlroots/COSMIC in progress). The bypass real apps use is
  reading `/dev/input` via **evdev** (compositor-independent) — which is exactly what our
  `hotkey.py` already does.
- **`always-on-top` as a window *flag* is a Wayland no-op for everyone** (confirmed for
  Qt, Tauri/tao, egui/winit, Slint). The only correct anchored-overlay mechanism is the
  **`wlr-layer-shell`** protocol — supported on KDE / wlroots (Sway, Hyprland) / COSMIC,
  **refused by GNOME/Mutter**. So a polished HUD is first-class on KDE/wlroots and
  *degraded on GNOME for any toolkit* → we ship a documented "reduced HUD mode" on GNOME
  (graceful-degradation doctrine).
- **Text injection is stack-independent**: X11 `xdotool`; Wayland `ydotool` (uinput, works
  on GNOME, needs a daemon) or `wtype` (virtual-keyboard, wlroots-only) or clipboard-paste
  fallback. Lives in our core regardless of UI.
- **A production twin already exists**: [`oddlama/whisper-overlay`](https://github.com/oddlama/whisper-overlay)
  — GTK4 + wlr-layer-shell + evdev + virtual-keyboard + Python faster-whisper. Almost our
  exact stack, already working. The architecture is proven.

**Consequence:** the UI framework only has to *render the settings window and paint the HUD
content*. Pick it on rendering + ecosystem + cross-device reach, not on plumbing it can't
give us anyway.

## 1. Fork — the default UI (replacing aging PySide/QtWidgets)

**Decision: finalists are pywebview and PySide6+QML; leaning pywebview. Resolve with a
spike (see §5).** The deciding axis is **maximum compatibility across laptop + desktop +
Android**.

| Option | ++ | -- |
|---|---|---|
| **pywebview + localhost Réglages** (lean) | smallest bundle, fast start, core untouched, prettiest live-partial HUD via DOM; localhost settings page renders on Android's browser too — the most cross-device-uniform surface | WebKitGTK transparency is compositor-quirky (test KDE vs GNOME); we hand-roll hotkey (pynput/evdev, already have it) + tray (pystray). "Quirky" is acceptable *because it's ours to fix/maintain.* |
| **PySide6 + QML** (steelman) | boring/safe/here-in-5-years; best-in-class native tray; official Android wheels since 6.8; QML/Qt Quick theming kills the "ugly Qt" rap (Telegram Desktop is QML) | PyInstaller bundle bloat (against the "works on the train" bar); hand-rolled Wayland global shortcuts. The only real hesitation is Android-train FUD, not a concrete blocker. |

Rejected and why: **Tauri/Electron** lose on WebKitGTK/Chromium + the Wayland window
ceiling (Electron also wrong on RAM for an all-day HUD; click-through unsupported on
Linux). **iced + iced_layershell** is the *only* toolkit with a correct Wayland
always-on-top HUD (COSMIC ships on it) and is the dark-horse if we ever want to drop Python
from the hot path via `whisper-rs` — but it's a Rust UI rewrite with no first-class
Android, diverging from our all-Python reality. **Flutter** isn't native-Wayland (runs
under XWayland) and Google demoted desktop to maintenance.

**On Android reuse, the honest finding:** there is no clean desktop-UI framework that also
reuses our existing native Kotlin + whisper.cpp Android app. The genuinely shareable asset
across desktop and Android is the **whisper.cpp engine + a clean UI↔core protocol + shared
UX design** (HUD layout, cheat-sheet, command grammar) — not a UI widget toolkit. So: keep
the native Kotlin overlay on Android, share the protocol and the UX, and pick the desktop
UI purely on desktop merit. pywebview's localhost settings page is the one literal UI
artifact that also renders on Android — which is why it edges ahead on the "compatible
overall" axis.

## 2. Fork — the architecture: one core + four thin frontends

**Decision: commit to the full core + frontends split (the 10-step refactor in §4).**

We are already ~30% factored: the [portable-core audit](2026-06-27-portable-core-audit.md)
classified all ~9.6k LOC (30% portable IP / 12% optional NLP / 58% desktop-coupled), and
Android already mounts `src/` via Chaquopy and runs `pipeline.postprocess()` unchanged. The
refactor is **"name and CI-fence the boundary,"** not a rewrite (~8.5h for the core
extraction per the audit).

The load-bearing opinion: **`tuparles-core` is a pure-Python, stdlib-first library; nothing
in it may import PySide6 / sounddevice / faster_whisper / pynput / evdev.** Enforced
mechanically by an import-boundary test (shipped this session). The four products:

```
        ┌───────────────────── tuparles-core (pip + Chaquopy aar) ──────────────────────┐
        │  Engine PROTOCOL · pipeline.postprocess · commands/quickchat/rolepacks         │
        │  privacy/ · config_core+settings(schema,defaults) · languages/vocab/partials   │
        │  i18n strings · lexicon · voice-command grammar · eval · telemetry/history     │
        └──────────┬───────────────┬────────────────┬─────────────────────┬─────────────┘
                   ▼               ▼                ▼                     ▼ (Chaquopy embeds
           ┌──────────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐ CPython)
           │ TuParles.app │ │tuparles-svc │ │tuparles-server│ │  tuparles-android    │
           │ (GUI: HUD +  │ │ (headless   │ │ (HTTP /stt/,  │ │ (Kotlin UI +         │
           │  Réglages +  │ │  daemon +   │ │  WAV→text,    │ │  AudioRecord +       │
           │  tray)       │ │  socket/IPC)│ │  FastAPI)     │ │  whisper.cpp JNI)    │
           └──────┬───────┘ └─────┬───────┘ └──────┬───────┘ └──────────┬───────────┘
                  │  share engine/audio/delivery/  │                    │
                  └────────┬──hotkey/capability─────┘            engine = whisper.cpp (JNI)
                  ┌────────▼─────────┐
                  │ tuparles-desktop │  engine impls: CUDA→qwen→whisper.cpp (the gradient)
                  └──────────────────┘
```

`.app` and `-service` are **one desktop runtime** — the GUI is an optional layer over the
daemon. `-service` is literally `.app --headless` with an IPC endpoint. Don't make them two
codebases.

**Config sharing:** one schema, four readers. Author toggles in Python `settings._DEFAULTS`
(with their rationale prose — that's documentation), use Pydantic *at build time only* to
emit a committed `settings.schema.json` SSOT, runtime reader stays stdlib `json`, Kotlin is
**generated** from the JSON via quicktype in CI with a `git diff --exit-code` gate. New
toggle = one entry, schema regenerates, all four targets see it.

**UX/string sharing — data, not code:** lexicon table → `core/data/lexicon.json` (Python
keeps the regex engine; Android calls it via Chaquopy; webview displays the JSON).
Voice-command grammar → data, parser stays core Python (the safety interlocks live in ONE
place — never a divergent command parser on Android). i18n strings → `core/data/strings/{fr,en}.json`,
with Android `strings.xml` *generated* from it (native idiom = generated artifact;
everything dynamic reads shared data). Generation over duplication; CI diff-gates the
generated files so they can't silently lie.

**Repo strategy:** monorepo, packages inside, relative paths (already the case — `android/`
on `main` shares `src/`). **No git submodules** (re-introduces a version pin + "did you
update the pointer" failure). Models stay gitignored + fetched per rung.

## 3. Fork — the Python ↔ whisper.cpp boundary (CPU rung, #4)

**Decision: default to pywhispercpp (pybind); adopt ctypes only if the benchmark (#3)
shows a real latency margin worth the per-release maintenance tax.**

Both ctypes and pybind run **in-process with a persistent model**, so their hot-path
latency is essentially identical — "fastest" doesn't separate them at runtime. ctypes' only
edge is no build-time toolchain; its cost is hand-written struct bindings, brittle against
`whisper.h` churn (the per-release tax). So unless #3 surprises us, **pywhispercpp is the
sweet spot**: it restores `initial_prompt` vocab-biasing + per-word confidence that qwen
lost, runs in-process, uses the same GGML family as the GPU and Android rungs, and installs
via pip (musl/alpine = build from source, which the Android port already proved compiles).

| Approach | musl/alpine | Latency | Word-conf / prompt | Verdict |
|---|---|---|---|---|
| **pywhispercpp** | build from source on alpine | in-process, persistent | yes + yes | **desktop CPU + server muscle** |
| subprocess → CLI | static musl binary, like qwen today | ~0.65s spawn/take | only if CLI emits token JSON | erable-tiny shim / server fallback |
| ctypes → libwhisper.so | dlopen a musl `.so` | in-process, persistent | yes (struct reads) | **only if #3 proves a margin** |
| Chaquopy + JNI (Android) | N/A | native | engine-native | **android — keep as-is** |

faster-whisper/ctranslate2 stays the **GPU** rung (no musl wheels, best GPU throughput); the
engine flips at the GPU boundary exactly as the gradient note says. One GGML family
(`large-v3-turbo`) spans the CPU→GPU rungs.

## 4. The 10-step minimal-refactor path (lowest-risk, ordered, no big bang)

Each step ships independently and keeps the app green. Steps 1-5 are the spine (~1 week);
the existing app keeps running on `tuparles` (= core + desktop) throughout.

1. Finish `config.py` → `config_core` + desktop split (already ~half done — `config_core.py`
   exists; move `LEVEL_*` later; the namespace move in step 5 settles it). *Pure move.*
2. Make `settings._path()` injectable via `TUPARLES_CONFIG_DIR` env (one-liner; Android
   sets it to app storage).
3. **Add the import-boundary CI gate** — pytest importing every intended-core module with
   PySide6/sounddevice/faster_whisper/pynput/evdev poisoned in `sys.modules`. Build this
   *before* moving anything: it defines the boundary and catches leaks during steps 4-6.
   **(Shipped this session.)**
4. Lift the `Engine` Protocol + `Word`/`Transcription` dataclasses into core (leave impls in
   desktop).
5. Extract `tuparles-core` as a package; `tuparles` (desktop) depends on it.
   **(Shipped Sprint 26.)** Realised as a PEP 420 namespace split: two distributions
   under `packages/` sharing the `tuparles.` namespace (so imports/Android unchanged),
   a `package-mode=false` workspace root. Desktop path-depends on core (`develop=true`).
6. Externalize shared data (lexicon/strings/grammar → JSON in core; readers stay core).
7. Carve `tuparles-service` — extract the hotkey→record→decode→deliver loop from the Qt
   wiring so it runs headless + a thin socket/HTTP control surface. (Biggest single step.)
8. Generate config Kotlin + `strings.xml` from the SSOT in CI with a diff-gate; retire any
   hand-mirrored Kotlin config.
9. `WhisperCppEngine` (pywhispercpp) for the CPU rung (Task #4) — benchmark first (#3).
10. `tuparles-server`: FastAPI over core + `WhisperCppEngine`, the `/stt/v1/` dispatch shim
    (Tasks #5-7). Near-zero new logic — reuses postprocess, privacy, eval.

## 5. The order, and what's next

**Decision: arch → engine → UI.** Arch first because the core boundary makes everything
downstream (especially `tuparles-server`) cheaper and non-duplicative. Then the engine
spine (the actual differentiator). UI last — and the UI choice (pywebview vs PySide6+QML)
is **resolved by a spike**: prototype the `GlobalShortcuts` portal + a translucent
`wlr-layer-shell` HUD on the actual NVIDIA + KDE-and-GNOME box. Those two spikes will tell
us more than any further reading. The benchmark (#3) is pure measurement and can run anytime
— it feeds, not blocks, the engine work.

*The trail's half-cleared; "we make the road by walking it." Build the boundary so the next
reader — at 2am, on the train, on a phone — finds it already cleared.*

### References
- [pywhispercpp (PyPI)](https://pypi.org/project/pywhispercpp/) · [pywhispercpp docs](https://absadiki.github.io/pywhispercpp/)
- [whisper-overlay (production twin)](https://github.com/oddlama/whisper-overlay)
- [GlobalShortcuts portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html) · [GNOME 48 global shortcuts](https://ubuntuhandbook.org/index.php/2025/03/gnome-48-rc-global-shortcuts-hdr-luminance/)
- [wlr-layer-shell refused by GNOME (gnome-shell #1141)](https://gitlab.gnome.org/GNOME/gnome-shell/-/issues/1141) · [iced_layershell](https://crates.io/crates/iced-layershell)
- [datamodel-code-generator](https://github.com/koxudaxi/datamodel-code-generator) · [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)
