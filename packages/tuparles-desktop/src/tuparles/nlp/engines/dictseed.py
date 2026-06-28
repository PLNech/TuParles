"""Dict-seeding engine: which corpus terms to bias the STT decoder toward.

Application-specific scoring on top of the generic features. A term earns a
seed slot when it is both *prominent* in your code (RRF of symbol/tfidf/embed)
AND *hard* for Whisper (whisper_risk). A common French word is prominent but
risk ~ 0 -> not seeded; `getFacetValues` is both -> seeded high.

The output feeds two mechanisms (#68): faster-whisper `initial_prompt`/hotword
bias, and an opt-in post-decode correction. Both earn their place against the
FP/FN harness (#69) -- structural, never a blind confidence score.
"""

from __future__ import annotations

from dataclasses import dataclass

from tuparles.nlp.features import Corpus, TermStats
from tuparles.nlp.fuse import rrf, rrf_contributions
from tuparles.nlp.signals import (
    EmbeddingBackend,
    rank_embed,
    rank_symbol,
    rank_tfidf,
)


def whisper_risk(ts: TermStats) -> float:
    """0..1 heuristic: how likely Whisper mangles this token.

    Ordinary dictionary words decode fine; the trouble is code-shaped tokens --
    camelCase, snake_case, ALLCAPS acronyms, digit-mixed, long out-of-vocab
    identifiers. A transparent additive heuristic (not a confidence score) we
    can tune against the FP/FN harness. Accented real words get pulled down.
    """
    risk = 0.0
    if ts.is_camel:
        risk += 0.40
    if ts.is_snake:
        risk += 0.35
    if ts.is_acronym:
        risk += 0.30
    if ts.has_digit:
        risk += 0.20
    if ts.is_identifier:
        risk += 0.20
    if len(ts.surface) >= 12:
        risk += 0.10
    if ts.has_accent and not ts.is_identifier:
        risk -= 0.20
    return max(0.0, min(1.0, risk))


@dataclass
class SeedTerm:
    surface: str
    key: str
    seed_score: float  # final rank key: prominence gated by whisper-risk
    rrf_score: float  # fused prominence across signals
    whisper_risk: float
    salience: float
    tfidf: float
    signals: dict[str, float]  # per-signal RRF contribution (explainability)


def seed(
    corpus: Corpus,
    backend: EmbeddingBackend | None = None,
    *,
    min_count: int = 2,
    k: int = 60,
    top: int | None = None,
) -> list[SeedTerm]:
    """Rank corpus terms as STT seed candidates. `backend` adds the embed signal."""
    cands = corpus.candidates(min_count)
    if not cands:
        return []
    rankings: dict[str, list[str]] = {
        "symbol": rank_symbol(cands),
        "tfidf": rank_tfidf(cands),
    }
    if backend is not None:
        emb_rank, _ = rank_embed(cands, backend)
        rankings["embed"] = emb_rank
    fused = dict(rrf(rankings, k))
    out: list[SeedTerm] = []
    for ts in cands:
        rrf_score = fused.get(ts.key, 0.0)
        risk = whisper_risk(ts)
        out.append(
            SeedTerm(
                surface=ts.surface,
                key=ts.key,
                seed_score=rrf_score * (0.25 + 0.75 * risk),
                rrf_score=rrf_score,
                whisper_risk=risk,
                salience=ts.salience,
                tfidf=ts.tfidf,
                signals=rrf_contributions(rankings, ts.key, k),
            )
        )
    out.sort(key=lambda s: -s.seed_score)
    return out[:top] if top else out
