"""The post-decode text pipeline, in one place.

The daemon and the eval harness must run the *identical* post-processing, or
the test measures a fiction the user never sees. So the order lives here, once:

1. spoken punctuation — operates on the spoken words ("virgule") before any
   later stage rewrites them
2. lexicon — deterministic fixes for caught-red-handed mishears
3. repeat-collapse — sentence-level, needs the (near-)final text to group runs
4. casing — re-case to the user's style (#120); last, on the final text, and an
   identity no-op unless they opt into a style (default `preserve`)

Whatever the daemon does to `Transcription.text` to get user-facing text, it
does by calling this. Keep it that way.
"""

from collections.abc import Callable

from tuparles import syntax_features  # noqa: F401  (import = register families)
from tuparles.casing import apply_casing
from tuparles.lexicon import apply_lexicon
from tuparles.punctuation import apply_spoken_punctuation
from tuparles.repeats import collapse_repeats
from tuparles.syntax import SyntaxContext, apply_syntax


def postprocess(
    text: str,
    ctx: SyntaxContext | None = None,
    on_syntax_fire: Callable[[str], None] | None = None,
) -> str:
    """Raw ASR text → the exact string the user gets pasted/typed.

    Spoken punctuation maps the dictated words first; the lexicon fixes known
    mishears; the spoken-syntax families (#53 — quotes, caps, lists, code) then
    rewrite their triggers; repeat-collapse last, on the near-final text. `ctx`
    carries the output-format target (#58); None → plain, the safe default.

    `on_syntax_fire` is forwarded to the syntax stage as a pure side-effect
    hook (the daemon records telemetry; the eval harness omits it).
    """
    text = apply_lexicon(apply_spoken_punctuation(text))
    text = apply_syntax(text, ctx, on_fire=on_syntax_fire)
    text = collapse_repeats(text)
    return apply_casing(text)


def preview(text: str) -> str:
    """Display-only fidelity for a live partial: the pure text stages, so the
    bubble shows the product's own headline features *as they'll land* — spoken
    punctuation ("virgule" → ","), the caught mishears, and the spoken-syntax
    rewrites (the reported "slash impeccable" → "/impeccable") — instead of raw
    decoder words the final would then quietly fix (#132).

    Two stages of `postprocess` are deliberately dropped:

    - `collapse_repeats` — sentence-level, "needs the (near-)final text"
      (see above). On a sliding tail window a run straddling the window edge
      would collapse this tick and un-collapse the next: visible flapping for
      zero preview value.
    - telemetry — `on_fire` is left None so `syntax.used` stays final-only; a
      partial re-decodes ~1 Hz, and counting each tick would inflate the metric
      by an order of magnitude. `postprocess` (the daemon + eval harness path)
      is untouched, so the two never drift.

    NEVER followed by command parsing. `parse_command`/quick-chat are daemon
    steps (daemon.py), not pipeline stages — this module doesn't even import
    them — so a previewed partial *cannot* execute a command by construction:
    the safety interlocks (doubled trigger, length guard, literal escape —
    docs/research/2026-06-23-voice-commands-design.md) are never reached because
    that code simply isn't on this path. Partials are pixels, not intents.
    """
    text = apply_lexicon(apply_spoken_punctuation(text))
    text = apply_syntax(text, None, on_fire=None)
    return apply_casing(text)
