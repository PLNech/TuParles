# Preview-window UX review — the bubble, the long take, and the signals

*2026-07-11 · design study, no code changed. Method: impeccable design-review
(product register: the tool disappears into the task; motion conveys state;
attention is a budget). Every claim below cites the code read, the user's own
dictated words, or the methodology.*

Primary evidence, dictated through the tool itself:

> "This is becoming a very long text, and I'm not seeing the beginning of the
> text anymore. […] I have the impression we should spread horizontally, to
> the right of the screen and the left of the screen. Horizontal space is so
> big on those laptops and we're not really making much of it. I understand we
> don't want to take up vertical space […] But what we want here is to be able
> to have an overview of what we typed."

The user is right, and the code confirms it — in a sharper way than they
could see from outside.

---

## 1. Current-state map

All references are `packages/tuparles-desktop/src/tuparles/ui.py` unless noted.

### Geometry

- **Fixed width, always**: `WIDTH, HEIGHT = 460, 56` (ui.py:36),
  `setFixedSize(WIDTH, HEIGHT)` (ui.py:200). The width never changes in any
  state, any view, any screen size. On a 1920 px laptop the bubble uses
  **24 % of the horizontal axis**; on a 3840 px external, 12 %.
- **Anchor**: bottom-centre of the resolved screen, `MARGIN_BOTTOM = 64` px
  above the edge (`_home_pos`, ui.py:360-366). Multi-monitor is genuinely
  well handled: `bubble_screen` = primary / cursor / focus / named / "all"
  mirror, resolved fresh each take (ui.py:114-138, settings.py:65;
  `BubbleGroup`, ui.py:718-843).
- **DPI**: all constants are raw pixels (460, 56, 300, font 10.5 pt at
  ui.py:204). Qt's device-pixel scaling keeps it crisp, but nothing is
  proportional to the screen — the same 460 px pill is "comfortable" on a
  1366 px panel and a postage stamp on a 4K monitor. There is no font-size
  knob.

### Text layout: the two views

- **Minimal** (opt-in pill): one line, `ElideLeft` while recording — freshest
  words visible, beginning *always* invisible (ui.py:534-538). The final
  flash flips to `ElideRight` ("this is what landed") — so on a long take the
  final shows only the *start* of text you were just watching the *end* of.
  A deliberate choice, but on takes past ~40 chars neither state ever shows
  the whole thing.
- **Full** (the default, settings.py:12): word-wraps into the text column and
  **grows vertically** from 56 px up to `MAX_HEIGHT = 300` px
  (`_desired_height`, ui.py:320-332), re-anchoring to stay above the bottom
  edge (`_apply_size`, ui.py:334-341). Past 300 px, the *oldest* words are
  trimmed behind an ellipsis via a cached bisection (`_trim_to_fit`,
  ui.py:540-570).

### The arithmetic that indicts the full view

The text column is `WIDTH − bars_end(132) − 14 − 24 ≈ 290 px` (ui.py:316-318)
— roughly **42 characters per line** at 10.5 pt. The 300 px cap holds ~15
lines ≈ **600 characters**, which is exactly why the daemon caps partials at
800 chars ("the bubble shows ~600 chars at most anyway", daemon.py:281-283).

So the current "full" view is a **460 × 300 px vertical tower**: 15 lines of a
42-char newspaper column, planted dead-centre over the very code the docstring
promises not to cover ("it deliberately avoids taking vertical space",
ui.py:1-11). It is the worst quadrant of the trade-off space: it spends the
scarce axis (vertical, over your working text) while wasting the abundant one
(horizontal, ~76 % of the bottom edge is empty), *and it still loses the
beginning* the moment a take passes ~600 chars. The user's complaint is not a
preference; it is a correct reading of the geometry.

### What is genuinely good (keep it)

- The colour doctrine is airtight and consistently applied: hue = silicon
  identity (green GPU / blue CPU), "landed" = brightness lift, never a hue
  switch (`_brighten`, ui.py:141-149; comment block ui.py:47-58). Red = error,
  amber = salvaged partial ("held, not failed", ui.py:56-58).
- Contrast passes: `_TEXT_LIVE` on `_BG` ≈ 12.8:1; `_TEXT_DIM` ≈ 5.0:1 —
  above the 4.5:1 floor even at 10.5 pt.
- No-focus discipline (`WA_ShowWithoutActivating`, `Qt.NoFocus`, ui.py:197-199),
  workspace stickiness (ui.py:376-399), fade choreography with re-grab glide
  (ui.py:239-248) — the "fades into background" intent is executed with care.
- `_trim_to_fit`'s O(1)-per-frame memoized bisection (ui.py:540-570) is the
  right engineering for a 30 fps paint path.

The bones are excellent. The failure is one layout decision: *grow up, not
out*.

---

## 2. The long-take overview problem

Frame it with the right user model: while speaking, the user **glances, they
do not read**. The glance has two questions: *"is it hearing me correctly
right now?"* (the tail) and, occasionally, *"did the whole thought survive?"*
(the overview). The current full view answers neither well past 600 chars:
the tail is buried at the bottom of a tower, and the overview is amputated.

### Options considered

**A. Horizontal ribbon (recommended).** The bubble stays anchored to the
bottom edge and **grows in width first**, symmetric from centre, up to a
fraction of the screen (default ~92 % of `availableGeometry().width()`).
Height grows only from 1 line (56 px) to 2 lines (~76 px), never more. When
even two full-width lines overflow (~460 chars at 1920 px), the older text
drops into a **compressed register**: line 1 renders the history smaller
(~8 pt) and dimmer (`_TEXT_DIM`), line 2 renders the live tail at full size
and brightness, right-anchored.

- *Cognitive load while speaking*: lowest of all options. The glance target —
  the freshest words — sits at a **fixed point** (end of the bright line),
  exactly where `ElideLeft` trained users to look today. The overview lives
  in peripheral vision as a dim strip; recency is encoded by
  **brightness + size**, which is precisely the house doctrine (hue stays
  identity; second states ride brightness — memory:
  `feedback-signal-more-by-brightness-not-hue`).
- *Capacity*: at 1920 px, text area ≈ 1596 px → ~230 chars on the bright
  line + ~290 on the compressed line ≈ **750+ chars fully visible, beginning
  intact** — beats the current tower's 600 with a quarter of its vertical
  footprint (76 px vs 300 px).
- *Don't-cover-the-code*: 76 px along the bottom edge covers a status bar and
  maybe one code line, vs the tower's 300 px over the editor's centre-bottom.
  Strictly better.
- *Implementation*: **M**. Everything lives in the existing custom
  `paintEvent` — no Qt layout system to fight. Needed: a `_desired_width()`
  sibling to `_desired_height()` (ui.py:320) driven by
  `fm.horizontalAdvance`, `_apply_size` re-centering on width change
  (ui.py:334), and a two-register paint in `_paint_text` (ui.py:498). The
  trim bisection is reused unchanged for the compressed register.

**B. Multi-column flow** (text flows into newspaper columns marching
rightward). Rejected: columns are a *reading* affordance, not a *glancing*
one — the eye must resolve reading order mid-sentence, and the live insertion
point jumps between columns. Highest cognitive load of the lot, and column
balance thrash at 1 Hz partial updates would flicker.

**C. Whole-take shrinking-font "minimap"** (everything visible, font scales
down as text grows). Self-defeating standalone: past ~800 chars in any sane
strip the font is sub-7 pt noise; you get the *shape* of the take but can
verify nothing. However, as the **compressed register inside option A** it is
exactly right — that dim 8 pt line *is* the minimap, bounded to text that
recently scrolled out of the bright line.

**D. Fade-out-but-scrubbable history** (hover/scroll the bubble to revisit).
Rejected for live use: scrubbing a no-focus overlay *while speaking* is an
absurd interaction (hands are the thing dictation frees), and post-take the
need is already served by the tray's Historique + « Copier la dernière »
(tray.py:85-98). Adding pointer interaction also erodes the bubble's
never-steals-focus guarantee — its most sacred property (Wayland already
fights it, daemon.py:246-255).

**E. Two-line full-width marquee.** Subsumed by A (A *is* this, plus the
compressed register instead of pure loss).

**F. Vertical side-dock** (right screen edge column). The user said
horizontal margins are free, and on ultrawides they are — but on the primary
target (16:10 laptop, editor maximised) there is no free side margin; a dock
covers code *worse* than the bottom edge. Worth offering later as a
`bubble_edge` override for ultrawide users, not as the default.

### Recommendation

**Primary: evolve the existing "full" view into the ribbon (A).** Don't add a
third mode — "full" already means "show me the whole take"; A is simply that
promise kept. Minimal (the discreet pill) stays untouched as the opt-in.
Per « c'est un réglage » — smart default, total override:

| Réglage | Défaut | Rôle |
|---|---|---|
| `bubble_max_width` — « Largeur du bandeau » | `0.92` (fraction of screen; `0` = current 460 px fixed) | the total-override for people who liked the pill footprint |
| `bubble_lines` — « Lignes du bandeau » | `2` (`1` = single strip, no compressed register) | motion/height sensitivity |
| `bubble_font_pt` — « Taille du texte » | `10.5` | the missing accessibility knob; also the HiDPI escape hatch |

**Fallback (if M is too big for the sprint): S-sized palliative** — keep the
tower but (a) halve `MAX_HEIGHT` to ~150 px and (b) widen `WIDTH` to a screen
fraction (~60 %), turning 15×42 into ~6×130 — same ~600-char capacity, third
of the occlusion, and lines long enough to skim. It is one constant-to-
function change plus `_home_pos` centring. Not the destination, but strictly
better than today.

---

## 3. Partials fidelity: the display-only postprocess seam

**Verified as diagnosed.** Partials ship raw decoder text:
`transcribe_partial` → 800-char cap → `self._bridge.partial.emit(text)`
(daemon.py:275-285). `postprocess()` runs only in `_finish`
(daemon.py:398-401). Hence "slash impeccable" painted literally while the
final correctly delivered "/impeccable".

**The structural good news: the command layer is already outside
`postprocess`.** `parse_command` and quick-chat expansion are separate daemon
steps (daemon.py:405, 413; `tuparles/commands.py`), not pipeline stages. So
running `pipeline.postprocess`-style text stages on partials **cannot execute
a command** — the safety doctrine's interlocks (doubled trigger, length
guard, literal escape — `docs/research/2026-06-23-voice-commands-design.md`)
are untouched because that code is simply never called on the partial path.
The seam is safe by construction, not by care.

### Stage-by-stage verdict (pipeline.py:42-45)

| Stage | On partials? | Why |
|---|---|---|
| `apply_spoken_punctuation` | **Yes** | Pure word→symbol rewrite; this is the fidelity the user actually watches ("virgule" → ","). |
| `apply_lexicon` | **Yes** | Deterministic mishear fixes; conservative by charter. |
| `apply_syntax` (slashes, quotes, caps — `syntax_features/`) | **Yes, with `on_fire=None`** | Pure rewrites (`apply_syntax` is pure unless the hook is injected, syntax.py:128-131). This fixes the reported "slash impeccable" literally. Omitting the hook keeps `syntax.used` telemetry final-only — no double counting. |
| `collapse_repeats` | **No** | Sentence-level, "needs the (near-)final text" (pipeline.py:9). On a sliding tail window (daemon.py:268-269) a repeat straddling the window edge would collapse, then un-collapse next tick — visible flapping for zero preview value. |
| `apply_casing` | **Yes** | Identity under the default `preserve` (settings.py:47); if the user opted into a style, the preview should look like what will land. |

### Precise seam

Add to `packages/tuparles-core/src/tuparles/pipeline.py` (next to
`postprocess`, so the two can never drift silently):

```python
def preview(text: str) -> str:
    """Display-only fidelity for live partials: the pure text stages, no
    telemetry, no repeat-collapse (unstable on a sliding window). NEVER
    followed by command parsing — partials are pixels, not intents."""
    text = apply_lexicon(apply_spoken_punctuation(text))
    text = apply_syntax(text, None, on_fire=None)
    return apply_casing(text)
```

In `_partials_loop` (daemon.py:284-285): keep `self._last_partial = text`
**raw** (miss-forensics at daemon.py:491 wants what the decoder said, not the
prettified version), and emit `preview(text)` to the bridge. One consequential
decision: `_recover_with_partial` (daemon.py:507-526) copies the salvaged
partial to the clipboard — run `preview()` there too, so *what you saw amber
is what Ctrl+V pastes*. The bubble showed the previewed string; pasting the
raw one would be a silent recant of the pixels.

Cost: regex passes over ≤800 chars at ~1 Hz — noise. One known edge: the
800-char cap truncates *before* preview, so a trigger word split at the cut
edge may render oddly for one tick; display-only, self-healing, acceptable.

Knob, per doctrine: `partials_preview` — « Aperçu fidèle (ponctuation en
direct) », default **on** (the user filed the discrepancy as a defect, which
is what it is).

---

## 4. Notification & signal audit

Inventory of every signal the system can emit today:

| Event | Channel | Register | Dwell / persistence | Gate |
|---|---|---|---|---|
| Recording live | Bubble appears + live bars; tray hue full | ambient | while recording | always |
| Partial text | Bubble text | ambient | live | always (CPU: `cpu_partials_enabled`) |
| Decoding | Bar sweep + tray pulse; "(Ns)" badge past 3 s (ui.py:62, 165-171) | ambient | while decoding | always |
| Take landed | Brightened flash, `ElideRight` | transient | 1.4 s (ui.py:267) | always |
| Edit command ran | `bridge.command` → **`show_final`** (daemon.py:643) | transient | 1.4 s | always |
| GPU→CPU fallback | Same toast channel, « Passé sur CPU — un peu plus lent » (daemon.py:89-96, 472-478) | transient, **once per session** | 1.4 s | `backend_toast` |
| Error / queue full | Red text (`show_error`; « File pleine (N) — patiente », daemon.py:182) | transient | 2.5 s | always |
| Salvaged partial | Amber + « Ctrl+V » badge | transient | 2.8 s | always |
| Queue backlog | Chips strip (ui.py:573-715) | ambient | while queued | `queue_chips` |
| Backend identity | Green/blue hue everywhere | ambient | continuous | always |
| Dev raw capture | Steady red dot + tooltip warning (tray.py:25-27, 185-191) | ambient | while armed | dev only |
| Start cue | Soft tick (cue.py) | audible | 90 ms | `start_cue_sound`, opt-in |

### Finding 1 — register confusion: status toasts wear the transcript's costume

`bridge.command.connect(bubble.show_final)` (daemon.py:643) means an edit
confirmation, the CPU-fallback notice, and *actual landed text* all render
identically: bright `_TEXT_LIVE`, brightened-bar "delivered" flash. The flash
*means* "this text just went into your window" (ui.py:47-58) — so « rien à
ajuster » or « Passé sur CPU… » momentarily claims it was pasted. The
impeccable product register calls this an inconsistent component vocabulary:
one visual word, two meanings. Fix is small: a `show_status(msg)` state that
paints dim, skips the bar-brighten, maybe prefixes « · » — status whispers,
transcripts shine.

### Finding 2 — the transient channel silently swallows announcements

`show_final`, `show_error`, and `show_recovered` all early-return while
`state == "recording"` (ui.py:259-260, 270-271, 284-285). Deferring to the
live take is right for *transcript* flashes — but it also eats **errors** and
the **one-per-session CPU toast** during back-to-back dictation, and
`_backend_announced` is set True regardless (daemon.py:477): if you were
already speaking the next take when the fallback landed, the notice is
**gone for the session**. This is the exact anatomy of "the GPU→CPU
degradation went unnoticed for two days": a *persistent state* was assigned a
*transient channel*, and the transient channel has a documented drop path.
The parallel tray fix addresses the state half; the system half worth fixing
here is a one-slot pending-toast that re-fires on the next idle instead of
dropping. Principle: **transient channels for events, persistent channels for
states, and any dropped signal must be re-queued, not forgotten** — the
project already learned this for data ("record misses harder than
successes"); it applies to signals identically.

### Finding 3 — the sound channel is asymmetric in the wrong direction

The only audible signal is the *start* cue (opt-in, cue.py). But a start is
the moment the user is by definition looking at the tool they just triggered
— the visual cue is near-sufficient. A **failure** is the opposite: eyes may
be on notes, on a second screen, mid-glance elsewhere; a 2.5 s red flash on a
bottom-edge strip is missable, and per Finding 2, sometimes not even shown.
Successes are self-evident (text appears in your window); failures are the
signals that must not depend on a well-timed glance. Proposal: an opt-in
« Son d'erreur » — a short *descending* blip (the start cue's mirror), same
synthesized-not-shipped approach, same defensive silence. Default off, like
the start cue: a quiet local tool shouldn't beep uninvited.

### Where more signal would be noise

- A per-take "delivered" sound or toast: the pasted text *is* the
  notification. Nothing to add.
- Chips for a queue of one: already handled — with a fast GPU pending never
  exceeds 1, so the strip rarely appears (memory: Sprint 19), and it's
  opt-out. Correct as is.
- Announcing every partial-decode hiccup: correctly invisible today
  (daemon.py:277 — "a dropped partial is invisible; final decode rules").
- Mirror mode "all" multiplies motion ×N screens — fine because it is an
  explicit user choice, never a default.

### Accessibility side-notes (from the audit pass)

- No reduced-motion path: the bubble breathes/sweeps unconditionally
  (ui.py:344-349, 470-483). The tray has `tray_animation` (settings.py:71);
  the bubble deserves the same knob, honouring it in `_tick`. Impeccable is
  blunt here: reduced motion is not optional.
- 10.5 pt fixed with no override is the other gap — covered by
  « Taille du texte » in §2.

---

## 5. Quick wins vs structural — ranked for cherry-picking

| # | Item | Effort | User-visible payoff |
|---|---|---|---|
| 1 | `pipeline.preview()` on partials (§3) — punctuation/slashes/lexicon live, commands untouched | **S** | The preview stops lying about the product's own headline features; directly user-reported |
| 2 | Ribbon layout: "full" view grows wide-first, 2 lines max, compressed history register (§2-A) | **M** | *The* fix for the user's complaint: whole-take overview, beginning intact, 76 px instead of a 300 px tower over the code |
| 3 | Toast register split: `show_status` distinct from `show_final` (§4-F1) | **S** | Status messages stop impersonating delivered text; the CPU notice reads as a notice |
| 4 | Pending-toast re-fire on idle instead of silent drop while recording (§4-F2) | **S** | Errors and the one-shot CPU announcement survive back-to-back dictation — the "unnoticed for 2 days" class, closed system-side |
| 5 | « Taille du texte » (`bubble_font_pt`) + bubble animation knob (reduced motion) | **S** | Accessibility + HiDPI legibility; two settings, zero new concepts |
| 6 | Opt-in « Son d'erreur » descending blip (§4-F3) | **S** | Eyes-off failure awareness; mirrors existing cue.py pattern |
| 7 | Screen-fraction sizing throughout (folds into #2; standalone = the §2 fallback: wider, shorter tower) | **S–M** | Sane proportions on 1366 px through 4K without per-machine constants |
| 8 | Scrubbable/hoverable bubble history | **L** | Low: post-take needs are served by tray Historique; endangers the no-focus guarantee. **Defer indefinitely** |

Sprint-shaped suggestion: #1 + #3 + #4 are one S-day of seams and fix
everything *reported or diagnosed*; #2 is the M centrepiece that repays the
user's own words.

---

## 6. Mockups

### Stage 1 — short take: unchanged pill (nothing to fix)

```
                    ┌──────────────────────────────────────────┐
                    │ ▁▃▅▇▅▃  On ajoute le fallback CPU…       │  56 px · 460 px
                    └──────────────────────────────────────────┘
──────────────────────────────── bord d'écran ────────────────────────────────
```

### Stage 2 — the take grows: the ribbon widens along the bottom edge, one line

```
   ┌───────────────────────────────────────────────────────────────────────────────┐
   │ ▁▃▅▇▅▃  On ajoute le fallback CPU au deliver, then we ship the sidecar JSON a… │  56 px · jusqu'à 92 %
   └───────────────────────────────────────────────────────────────────────────────┘
──────────────────────────────── bord d'écran ────────────────────────────────
```

### Stage 3 — long take: two registers, recency = brightness + size, début visible

```
   ┌───────────────────────────────────────────────────────────────────────────────┐
   │ ▁▃▅▇▅▃  On ajoute le fallback CPU au deliver, then we ship the sidecar JSON    │  ← dim · 8 pt · l'historique
   │         avec les per-word probabilities, et là je vérifie que le début reste ▌ │  ← vif · 10.5 pt · la queue vivante
   └───────────────────────────────────────────────────────────────────────────────┘
──────────────────────────────── bord d'écran ────────────────────────────────
```

### Contrast: today's full view on the same take

```
                              ┌─────────────────────┐
                              │ ▁▃▅▇▅▃ …ship the    │
                              │   sidecar JSON avec │      300 px de haut,
                              │   les per-word      │      colonne de 42
                              │   probabilities, et │      caractères, posée
                              │   là je vérifie que │      sur le code —
                              │   le début reste    │      et le début est
                              │   visible           │      déjà coupé (…)
                              └─────────────────────┘
──────────────────────────────── bord d'écran ────────────────────────────────
```

### HTML mockup

A self-contained static page at laptop proportions (16:10) with a simulated
editor backdrop and the three ribbon stages vs the current tower, realistic
FR/EN code-switching text, house palette (green GPU bars, `_BG`/`_TEXT_LIVE`/
`_TEXT_DIM`):

`/tmp/claude-1000/-home-pln-Work-Tools-TuParles/de547369-7ba7-401d-a446-7b94d2399295/scratchpad/ribbon-mockup.html`

Serve over HTTP to view (Firefox blocks file:// in sandboxed dirs):
`python3 -m http.server 8123 --bind 127.0.0.1 --directory <scratchpad>` →
`http://127.0.0.1:8123/ribbon-mockup.html`. Not published anywhere.

*(Note: the impeccable context script reported NO_PRODUCT_MD for this repo;
its init flow was skipped deliberately — this study's write scope is this
report plus scratchpad mockups only.)*

---

## 7. Implementation addendum (shipped, Sprint 31 · `#132`)

The user validated the primary recommendation ("le ruban", option A) verbatim.
It shipped on the `preview-ribbon` branch (on top of the silence-trim work),
along with items #1 (the preview seam) and #4-F2 (the toast re-fire). What
landed vs the study:

- **§2-A — le ruban (item #2, M).** Built as recommended, entirely inside the
  existing custom `paintEvent`. The full view grows wide-first (`ribbon_widen`)
  up to `bubble_max_width` (default 0.92) before wrapping to at most
  `bubble_lines` (default 2). The compressed history register (dim `_TEXT_DIM`,
  ~0.78× the live point size) sits above the bright, right-anchored live tail —
  recency = brightness + size. Char budget `RIBBON_MAX_CHARS = 750`; oldest
  trimmed behind "…" past it. Every layout decision is a pure function
  (`plan_ribbon`, `ribbon_ceiling_width`, `ribbon_widen`, `ribbon_budget`,
  `fit_trailing_words`) with an injected `measure(str)->px`, headless-tested
  with a fake measurer — the paint pass only draws what they return, exactly the
  `chip_color`/`state_color` pattern the study praised. The anchor/multi-monitor
  logic was kept untouched, as recommended. Three knobs shipped with the French
  labels from the §2 table — « Largeur du bandeau » (0 = the fixed 460 px pill,
  the total override), « Lignes du bandeau » (1–3), « Taille du texte » (the
  missing accessibility/HiDPI point size) — all live, no restart.

- **§3 — `pipeline.preview()` (item #1, S).** Shipped as specified: the pure
  stages minus `collapse_repeats`, `on_fire=None`, next to `postprocess` so they
  can't drift. Confirmed safe *by construction* — a test asserts the command
  layer isn't even in the pipeline module's namespace. `_last_partial` stays raw
  for miss-forensics; `_recover_with_partial` previews what it salvages so the
  amber recant matches the pixels. `partials_preview` was NOT added as a knob:
  the discrepancy is a defect (the study's own framing), and preview() is pure +
  display-only + telemetry-free, so there is nothing to opt out of — one fewer
  setting to reason about beats a toggle for a bug fix. (Reconsider if a user
  ever wants to watch raw decoder output for debugging; a dev-mode escape hatch,
  not a user knob.)

- **§4 Finding 2 — pending status re-fire (item #4, S).** Shipped: a dedicated
  `status` bridge channel + `Bubble.show_status` with a one-slot pending toast
  that re-fires on the next idle (`_on_hide_timeout`), general to any status
  toast. `_backend_announced` is now honest (the notice is deferred, never
  dropped). Finding 1 (the `show_status` dim/no-bar-brighten *register* split)
  and Finding 3 (the error sound) were left for a later pass — out of scope for
  this change, which fixes the *drop path*, not the visual vocabulary. The
  tray's persistent-CPU-blue half (the study's companion) shipped in `#131`.

- **Deferred.** The queue-chip strip still anchors to the fixed `HEIGHT`, so on
  a 2-line ribbon it overlaps the ribbon's top ~20 px; chips almost never show
  with a fast GPU (Sprint 19) and re-anchoring needs a handle to the bubble's
  live height, so it was left as a known cosmetic. README screenshots still show
  the old tower (a committed PNG asset; regenerate with
  `scripts/readme_screens.py`).
