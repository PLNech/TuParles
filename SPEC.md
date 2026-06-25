# SPEC — Bubble UX & engine-status pass

> Handoff from the SRE/infra session (XPS22 install) to the app-code session.
> Captures **PLN's dictated feedback** (verbatim intent) + **diagnosis with
> file:line** + **proposed fixes & open decisions**. Implement in `src/`, update
> docs per `CLAUDE.md`'s standing duty (CHANGELOG/README/in-product help).
>
> Context: first real-world run on the XPS22 (Arch, **Plasma 6 Wayland/KDE**,
> RTX 2060, faster-whisper `large-v3-turbo` on CUDA). "Très très rapide, tourne
> très bien sur ce laptop." Code-switching FR/EN held up well.

---

## 0. Already done by the infra session (do NOT redo — host-level only)

These are **per-install workarounds outside `src/`**, applied on the XPS22.
The app-code decisions they imply are flagged in §1 and §5.

- **Bubble position** → launcher + autostart now run with `QT_QPA_PLATFORM=xcb`
  (`~/.local/share/applications/tuparles.desktop`, `~/.config/autostart/tuparles.desktop`).
  Workaround for the Wayland `move()` issue — see §1.
- **Full view default** → `~/.config/tuparles/settings.json` set to `{"view":"full"}`
  on this box. Product default still `minimal` (`settings.py:8`) — see §4.
- **Vocab seed** → `vocab.txt` got `Qwen, Whisper, faster-whisper, ctranslate2,
  ydotool, wl-clipboard, TuParles, Wayland, Plasma, Arch, Algolia, SuperCollider,
  TidalCycles, Ardour, GPU, CPU`. Cures "Qwen → couenne". See §6.

---

## 1. Bubble appears centre-screen, not bottom  ·  PLN: "elle s'affiche au milieu de mon écran et pas en bas"

**Root cause.** `Bubble._home_pos()` (`ui.py:183`) correctly computes a
bottom-centre point, but under **native Wayland the compositor ignores client
`move()`** — KWin places the frameless `Qt.Tool` window centred. Same reason
`_make_sticky()` (`ui.py:200`, uses `xprop`) is a silent no-op on native Wayland.

**Infra workaround in place:** run under XWayland (`QT_QPA_PLATFORM=xcb`) → both
`move()` and `xprop` work again. Good enough for this box; **verify after
re-login** that the bubble sits bottom-centre.

**App-code decision (cross-machine, pick one):**
- **(A) Document + enforce xcb** on Wayland (set `QT_QPA_PLATFORM=xcb` from the
  launcher/`install_desktop.sh`/entry-point when `XDG_SESSION_TYPE=wayland`).
  Cheapest, keeps the existing X11-isms (`xprop`) working. *My recommendation
  for now.*
- **(B) Native Wayland via `LayerShellQt`** (wlr-layer-shell; KWin supports it):
  proper edge-anchored overlay, no XWayland, real cross-compositor stickiness.
  Correct long-term but adds a dep + platform plumbing.
- At minimum: stop pretending `move()`/`xprop` work on native Wayland — detect
  and either bail to xcb or warn.

---

## 2. Mic volume barely moves  ·  PLN: "les points bougent à peine pendant que je parle"  ★ highest impact

**Root cause.** `audio.py:122-123`:
```python
rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
self.level = min(1.0, rms / 8000.0)
```
`indata` is int16 (±32768). Typical speech RMS ≈ 300–2000 → `level` ≈ 0.04–0.25,
and it's **linear**, so quiet/mid speech maps to almost-flat bars
(`ui.py:275` `half = 1.5 + level*max_half`).

**Proposed fix (perceptual + light gate):**
```python
NOISE_FLOOR = 80.0      # below this = silence, bars rest flat
FULL_SCALE  = 3000.0    # speech RMS that should peg the meter (tune on PLN's mic)
rms  = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
norm = max(0.0, (rms - NOISE_FLOOR) / (FULL_SCALE - NOISE_FLOOR))
self.level = min(1.0, norm ** 0.6)   # perceptual lift: quiet speech still visible
```
- Keep `FULL_SCALE`/`NOISE_FLOOR` as module constants (or settings) so they're
  tunable without a code dive.
- **Open decision:** fixed perceptual scale (above, predictable) **vs** a light
  **AGC** (track rolling peak, scale to it — always uses full range, adapts to
  mic gain, but can look "floaty"). *My take: ship the fixed perceptual + gate
  first; add AGC only if it still reads weak on his mic.*
- The 18-bar rolling deque (`ui.py:70`) is already a nice ~0.6 s scrolling
  history — this is purely an amplitude-mapping fix, leave the deque alone.

---

## 3. No "I'm working" feedback  ·  PLN: "un feedback d'animation pendant que tu travailles"

**Root cause.** The processing/idle animation exists but is too subtle.
`ui.py:272-276`:
```python
lvl = 0.18 + 0.14 * math.sin(self._phase + i * 0.45)   # gentle, low-amplitude ripple
```
`_phase += 0.16` per tick (`ui.py:180`). Reads as barely-alive, not "thinking".

**Proposed fix — a pulse that sweeps across the bars (clearly "scanning"):**
```python
# processing: a bright pulse travelling across the bars
center = (self._phase * 0.8) % BAR_COUNT
d = min(abs(i - center), BAR_COUNT - abs(i - center))   # wrap-around distance
lvl = 0.15 + 0.6 * math.exp(-(d * d) / 4.0)
```
- Makes `processing` visually distinct from `idle` and from the one-shot
  `final` green flash.
- Mostly visible on **long takes** (batched final decode ≈ 1 s); short takes are
  near-instant — that's fine, but it means the win is exactly PLN's "test assez
  long" case.
- **Open decision:** sweep (above) vs just bumping amplitude/speed of the
  existing breathing wave. *My take: the sweep — it actually says "busy".*

---

## 4. Long take = only ~5 words visible  ·  PLN: "à la fin je vois vraiment que 5 mots à la fois, j'ai du mal à me représenter ce que je suis en train de dicter"

**Root cause.** `minimal` view is one line, **elide-left** (`ui.py:303-307`) —
keeps the freshest words, drops the rest. By design, but on a long take it
starves PLN of context.

**Status.** `full` view already wraps and grows live to `MAX_HEIGHT=300`
(`_desired_height` `ui.py:152`, grows on each `set_partial`). Set as default on
this box via settings.json (§0).

**App-code decisions:**
- **Ship `full` as the product default?** (`settings.py:8`). *My take: yes for a
  dictation tool — seeing your take is the point. Keep `minimal` as the opt-in
  "discreet pill".*
- Or improve `minimal` to a **2-line** elide so there's more context without the
  big pill. (Lower priority if full becomes default.)
- Nice-to-have PLN hinted at ("me représenter ce que je dicte"): a tiny live
  **word-count / elapsed** readout in the corner of full view.

---

## 5. Engine colour: green=GPU, blue=CPU  ·  PLN: "une question de couleur, vert sur GPU, bleu sur CPU ?"

**Today.** Recording bars are fixed blue `_ACCENT` (`ui.py:41`, 122/162/247);
`final` flash green `_OK`; `error` red `_ERR`. So colour currently encodes
*state*, not *engine*.

**Proposed.** Make the bar colour an **ambient engine indicator**:
- **GPU active → green**, **CPU/qwen fallback → blue**. Keep red for error.
- `ResilientEngine` (`engine.py:187`) already knows the active backend and the
  fallback is **sticky for the session** ("drop to qwen-CPU for the rest of the
  session", `engine.py:200`) → simply colour by current backend: green until it
  ever falls back, blue after.
- **Wiring:** mirror the `level_source` pattern — pass a
  `backend_source: Callable[[], str]` ("gpu"|"cpu") into `Bubble.__init__`
  (`ui.py:49`), read it in `_paint_bars` (`ui.py:261`) to pick the base colour.
  Expose `ResilientEngine.active_backend` for it. (Avoid a per-take push signal;
  a pull source is simplest and matches the existing design.)
- **Open decisions:**
  - Does `final`/`processing` also take the engine colour, or stay
    success-green / state-coloured? *My take: recording+processing follow the
    engine colour; `final` stays the success-green flash (it means "landed"),
    `error` stays red. So green/blue = "which silicon", green-flash = "done".*
  - Define a distinct **CPU-green-flash vs blue** so the final flash doesn't
    collide with GPU-green. (Maybe final flash = brighter/whiter, engine =
    saturated.)
  - This noticeably changes the default look (blue→green while recording on
    GPU). Deliberate — flag in CHANGELOG.

---

## 6. Transliteration errors  ·  PLN: "la joie des erreurs de translittération… c'est vraiment une question de mots-clés et de seeding"

PLN's instinct is correct and **already the built-in mechanism**: `dictseed_bias`
(`settings.py:26`, #68) folds seed terms into Whisper's `initial_prompt`, and
`vocab.txt` is injected the same way. "Qwen → couenne / Quinn / Bill(build) /
CPP(C++)" = proper nouns/acronyms absent from the prompt.

- Infra already seeded `vocab.txt` (§0).
- App-code angle: the **codebase-aware dict-seeding** work
  (`docs/research/2026-06-24-codebase-aware-dict-seeding-eda.md`, #68) is exactly
  the durable fix — auto-harvest symbols like `Qwen`, `ctranslate2`, `ydotool`
  from the project so users don't hand-curate. Consider auto-suggesting tool/lib
  proper nouns. (No action required here; noting the through-line.)

---

## Priority (my recommendation)
1. **§2 volume meter** — small, high-impact, zero design risk.
2. **§5 engine colour** — PLN explicitly asked; medium wiring.
3. **§3 processing pulse** — small, mostly long-take payoff.
4. **§4 full-view default** — one-line default flip + decide minimal's fate.
5. **§1 Wayland positioning** — decide xcb-document vs LayerShellQt (infra
   workaround holds meanwhile).

## Don'ts
- The infra session left repo WIP **untouched** (`delivery.py`, `install.sh`,
  `setup_wayland.sh`, `install_desktop.sh`, `README.md`, `CHANGELOG.md` were
  already modified by the app-code session). Reconcile/commit that first so this
  pass lands on a clean tree.
- Per `CLAUDE.md`: ship doc updates (CHANGELOG `#NN`, README if user-visible,
  cheat-sheet) **in the same change**.
