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

# Hard cap on the assembled prompt. A stuffed prompt doesn't merely waste
# budget — codebase identifiers (ALL_CAPS_CONSTANTS, CamelCase) bias the
# decoder toward spelling words out letter by letter. The 2026-06-25 seed
# ablation measured this: the FULL regime (manual + ~26 auto-seeds, 747 chars
# / ~190 tokens) scored WORSE than manual-only (355 chars) on the code-switch
# eval AND hallucinated outright ('J.V.U.K.W.N…'), breaking a case the curated
# prompt passed. So cap well under Whisper's own ~224-token tail-keep. Only
# auto-seeds are trimmed (least-important first); the curated manual glossary
# is never dropped — it is the point. See
# docs/research/2026-06-25-transliteration-forensics.md.
_PROMPT_CHAR_BUDGET = 400

# A tiny command-vocabulary seed (#53). The 2026-06-28 take replay
# (docs/research/2026-06-28-spoken-slash-commands.md) proved this rescues the
# worst command mishear — "slash precompact" decoded as "c'est l'âge prix
# compact" → "/pre-compact" — WITHOUT the URL hallucination a broader, URL-
# example seed caused (it invented facebook.fr/google.com on take 23). So it is
# deliberately command-WORDS-only, and rides the protected tail with the manual
# glossary, never trimmed. Gated by the bias setting like every other seed.
COMMAND_SEED: list[str] = [
    "slash",
    "slash help",
    "slash compact",
    "slash precompact",
    "slash code review",
    "slash security review",
]


def _manual_glossary() -> list[str]:
    """The hand-curated personal glossary (vocab.txt), comments stripped."""
    if not VOCAB_FILE.exists():
        return []
    return [
        w.strip()
        for w in VOCAB_FILE.read_text(encoding="utf-8").splitlines()
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
        seeds = json.loads(cached[-1].read_text(encoding="utf-8")).get("top_seeds", [])
    except (OSError, ValueError):
        return []
    return [s["surface"] for s in seeds[:limit] if s.get("surface")]


def initial_prompt(
    manual: list[str] | None = None,
    seeds: list[str] | None = None,
    commands: list[str] | None = None,
    *,
    bias_enabled: bool | None = None,
) -> str | None:
    """`Glossaire : …` for Whisper, or None when there's nothing to bias toward.

    Order: auto-seeds (trimmable) first, then the command seed, then the manual
    glossary last — the tail wins Whisper's 224-token tail-keep and dedup, so the
    hand-curated terms are the most protected. The command seed rides just ahead
    of manual and, like it, is never trimmed by the budget (it's tiny and
    measured). Args are injectable for tests; production passes none — pass
    `commands=[]` to opt a test out of the built-in command seed.
    """
    manual = _manual_glossary() if manual is None else list(manual)
    if bias_enabled is None:
        bias_enabled = bool(settings.get("dictseed_bias"))
    if not bias_enabled:
        # bias off → no seeding at all, even if seeds/commands were passed
        seed_list: list[str] = []
        cmd_seed: list[str] = []
    else:
        seed_list = _seed_surfaces() if seeds is None else list(seeds)
        cmd_seed = COMMAND_SEED if commands is None else list(commands)

    manual_keys = {w.casefold() for w in manual}
    fresh_seeds = [s for s in seed_list if s.casefold() not in manual_keys]
    protected = cmd_seed + manual  # never trimmed; manual at the very tail

    # Trim auto-seeds (least-important first — they are ranked, so drop the
    # tail) until the whole prompt fits the budget. The command seed and manual
    # glossary are never dropped: they survive this trim and Whisper's own
    # ~224-token tail-keep.
    def _render(seeds: list[str]) -> str:
        return f"Glossaire : {', '.join(seeds + protected)}."

    while fresh_seeds and len(_render(fresh_seeds)) > _PROMPT_CHAR_BUDGET:
        fresh_seeds = fresh_seeds[:-1]

    return _render(fresh_seeds) if (fresh_seeds or protected) else None
