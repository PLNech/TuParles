# TuParles — working notes for contributors (human and otherwise)

Local push-to-talk dictation for Fr-En code-switchers. Speak, see, ship.
GPU-first (RTX 4080, faster-whisper large-v3-turbo), qwen-CPU fallback. X11 and
Wayland. Everything runs on your own silicon — that is the whole point.

## The standing duty: keep the docs honest

**When something big ships or behaviour changes, update the docs in the same
change — not "later".** That means, as applicable:

- `CHANGELOG.md` — a sprint entry (Added/Changed/Fixed/Infra/Doctrine, `#NN`).
- `README.md` — if a user-visible feature, flag, or setup step changed.
- `docs/research/` — a build note when a decision is worth remembering (why,
  not just what); these seed the eventual blog (#42).
- In-product help — the cheat-sheet, first-run wizard, and voice tutorial
  (EPIC #55) are documentation too. A new spoken command nobody can discover
  is a command that does not exist.

The README that lies is worse than the README that is missing: it costs the
reader the time to find out. If you change behaviour and can't update the docs
now, say so in the PR/commit rather than letting them drift.

## Principles that have paid off (and now guide the moats)

- **"It's a setting" — smart default, total override.** Every new behaviour
  ships with a sensible context-aware default AND a Réglages toggle. We don't
  argue about the One True Default; we pick a good one and expose the knob.
- **Safety is structural, not statistical.** The command-vs-text problem
  (#41, #53) is solved with hard interlocks — a doubled trigger, a length
  guard, a conditional escape — never a confidence score. The bias is
  asymmetric and absolute: *when in doubt, it's text.* See
  `docs/research/2026-06-23-voice-commands-design.md`.
- **A wrong autocorrect is worse than a visible mishear.** The lexicon and any
  dict-seeding correction (#54) stay conservative; we'd rather you see a
  mistake than have us silently rewrite your meaning.
- **Measure before you trust.** New decode behaviour earns its place against
  the code-switch eval (`tests/test_codeswitch_eval.py`, corpus in
  `tests/data/codeswitch/`). Forensics — journal `take:` breakdown + history
  DB — before theory.
- **The differentiator is where your voice lives afterward.** Local, on your
  box. Build for the silicon and the privacy story writes itself.
- **French-snappy where it reads well** (`dicte`, `Réglages`) — this is a
  bilingual tool; the surface should feel it.

## Conventions

- Python via `poetry`; `ruff` clean; tests with `pytest` (GPU tests marked
  `gpu`, deselected by default — run with `pytest -m gpu`).
- The post-decode text path lives in `pipeline.postprocess()`; the daemon and
  the eval harness both call it so they can't diverge.
- Identity/push rules and hardware specifics live in the session memory, not
  here. Don't commit credentials or model weights (see `.gitignore`).
