"""Dict-seed feed (#68): build Whisper's `initial_prompt` from your glossary
plus the codebase's seed terms, so the decoder spells `getFacetValues` right.

This is the BIAS half of the feed — advisory context Whisper treats as preceding
text. It can only nudge decoding, never force it, so it ships on by default
behind a setting. The risky half (a post-decode correction that *rewrites* the
transcript) is deliberately NOT here: it earns its place against the FP/FN
harness first (#69), per "a wrong autocorrect is worse than a visible mishear".

Whisper keeps only the LAST ~224 tokens of the prompt, so the curated manual
glossary goes at the TAIL — if the combined list overflows, your hand-picked
words survive and the auto-seeds are what get truncated.
"""

from __future__ import annotations

import json

from tuparles import settings
from tuparles.config import REPO_ROOT, VOCAB_FILE

# initial_prompt has a ~224-token budget shared with the glossary; cap the
# auto-seeds so a big codebase can't crowd out the manual terms.
_SEED_LIMIT = 30


def _manual_glossary() -> list[str]:
    """The hand-curated personal glossary (vocab.txt), comments stripped."""
    if not VOCAB_FILE.exists():
        return []
    return [
        w.strip()
        for w in VOCAB_FILE.read_text().splitlines()
        if w.strip() and not w.lstrip().startswith("#")
    ]


def _seed_surfaces(limit: int = _SEED_LIMIT) -> list[str]:
    """Top dict-seed surfaces from the most recent cached codebase EDA, or [].

    Reads what `scripts/nlp_eda.py` already writes; degrades to [] (manual-only,
    the prior behaviour) on a non-dev install or any read error. Live
    per-project selection is #70 — this just consumes the cache."""
    data_dir = REPO_ROOT / "docs" / "research" / "data"
    cached = sorted(data_dir.glob("*-nlp-eda.json")) if data_dir.is_dir() else []
    if not cached:
        return []
    try:
        seeds = json.loads(cached[-1].read_text()).get("top_seeds", [])
    except (OSError, ValueError):
        return []
    return [s["surface"] for s in seeds[:limit] if s.get("surface")]


def initial_prompt(
    manual: list[str] | None = None,
    seeds: list[str] | None = None,
    *,
    bias_enabled: bool | None = None,
) -> str | None:
    """`Glossaire : …` for Whisper, or None when there's nothing to bias toward.

    Auto-seeds first, manual glossary last (manual wins on dedup and survives the
    224-token tail-keep). Args are injectable for tests; production passes none.
    """
    manual = _manual_glossary() if manual is None else list(manual)
    if bias_enabled is None:
        bias_enabled = bool(settings.get("dictseed_bias"))
    if not bias_enabled:
        seed_list: list[str] = []  # bias off → never seed, even if seeds passed
    elif seeds is not None:
        seed_list = list(seeds)
    else:
        seed_list = _seed_surfaces()

    manual_keys = {w.casefold() for w in manual}
    fresh_seeds = [s for s in seed_list if s.casefold() not in manual_keys]
    words = fresh_seeds + manual  # manual at the tail (curated, truncation-safe)
    return f"Glossaire : {', '.join(words)}." if words else None
