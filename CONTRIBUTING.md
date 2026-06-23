# Contributing to TuParles

Merci! This is a small, opinionated tool — contributions are welcome when
they keep it small and opinionated.

## Dev setup

```bash
git clone https://github.com/PLNech/TuParles && cd TuParles
poetry install
poetry run pytest          # 109 tests, sub-second
poetry run ruff check src tests scripts
```

The full app additionally needs the system deps and model weights —
`install.sh` is the reference for that. But you can work on most of the
codebase without ever loading a model.

## Architecture in one breath

`hotkey` fires → `daemon` orchestrates → `audio` records → `engine`
transcribes (GPU faster-whisper primary, vendored qwen-asr CPU fallback) →
`punctuation` + `lexicon` + `repeats` post-process → `delivery` types into
focus → `history` remembers. `ui` (bubble) and `tray` watch via Qt signals.

## Testing philosophy

Two tiers, on purpose:

- **Pure layers** (`punctuation`, `lexicon`, `repeats`, `history`,
  `settings`): fully unit-tested, run everywhere, CI-gated. New
  post-processing logic MUST come with tests — including cases proving it
  *doesn't* fire on legitimate speech.
- **Hardware layers** (`engine`, `audio`, `ui`, `tray`, `hotkey`,
  `delivery`): exercised by humans dictating. CI can't hear you scream.

## Doctrine (the opinions)

- **A wrong autocorrect is worse than a visible mishear.** Post-processing
  is conservative: deterministic, word-boundary-aware, protected-phrase
  shielded. If a rule needs a probability, it probably needs a rethink.
- **Local-only.** Nothing the user says ever leaves the machine. Features
  requiring cloud calls don't land.
- **Code-switching is a first-class citizen**, not an edge case. Test
  fixtures mix français and English on purpose.
- **The UI fades into the background.** No windows that steal focus, no
  configuration palaces. One bubble, one tray glyph.

## PRs

- Keep them scoped: one behavior change per PR.
- `pytest` + `ruff check` green.
- If you touched the UI, regenerate the README screens:
  `QT_QPA_PLATFORM=offscreen poetry run python scripts/readme_screens.py`
- Describe what you *heard* vs what *landed* for transcription-quality
  changes — real dictation samples beat synthetic ones.
