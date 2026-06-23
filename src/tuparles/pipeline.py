"""The post-decode text pipeline, in one place.

The daemon and the eval harness must run the *identical* post-processing, or
the test measures a fiction the user never sees. So the order lives here, once:

1. spoken punctuation — operates on the spoken words ("virgule") before any
   later stage rewrites them
2. lexicon — deterministic fixes for caught-red-handed mishears
3. repeat-collapse — sentence-level, needs the (near-)final text to group runs

Whatever the daemon does to `Transcription.text` to get user-facing text, it
does by calling this. Keep it that way.
"""

from tuparles.lexicon import apply_lexicon
from tuparles.punctuation import apply_spoken_punctuation
from tuparles.repeats import collapse_repeats
from tuparles import syntax_features  # noqa: F401  (import = register families)
from tuparles.syntax import SyntaxContext, apply_syntax


def postprocess(text: str, ctx: SyntaxContext | None = None) -> str:
    """Raw ASR text → the exact string the user gets pasted/typed.

    Spoken punctuation maps the dictated words first; the lexicon fixes known
    mishears; the spoken-syntax families (#53 — quotes, caps, lists, code) then
    rewrite their triggers; repeat-collapse last, on the near-final text. `ctx`
    carries the output-format target (#58); None → plain, the safe default.
    """
    text = apply_lexicon(apply_spoken_punctuation(text))
    text = apply_syntax(text, ctx)
    return collapse_repeats(text)
