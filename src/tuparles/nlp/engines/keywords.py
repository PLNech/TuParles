"""Keyword / tag-cloud engine -- mainly for the prose & chat-history corpora.

Two rented methods and one homegrown view:

* `yake_keyphrases` -- YAKE: statistical, multilingual, no stopword config.
  A strong FR+EN baseline that needs no model. Lower score = more relevant.
* `embedding_keyphrases` -- the KeyBERT *method*: candidate n-grams ranked by
  cosine to the whole-document embedding, with MMR for diversity. Run on our
  own embedding backend (fastembed) rather than pulling KeyBERT's torch stack.
* `tag_cloud` -- aggregate term weights straight off the Corpus (salience or
  TF-IDF), normalised 0..1 for font sizing.
"""

from __future__ import annotations

import re

import numpy as np

from tuparles.nlp.features import Corpus
from tuparles.nlp.signals import EmbeddingBackend, _l2norm

_TOKEN = re.compile(r"[A-Za-zÀ-ſ][A-Za-zÀ-ſ0-9'_-]+")


def yake_keyphrases(
    text: str, lang: str = "en", top: int = 20, ngram: int = 3, dedup: float = 0.9
) -> list[tuple[str, float]]:
    """YAKE keyphrases. Returns (phrase, score); LOWER score = more relevant."""
    import yake

    extractor = yake.KeywordExtractor(lan=lang, n=ngram, top=top, dedupLim=dedup)
    return extractor.extract_keywords(text)


def _ngram_candidates(text: str, ngram: tuple[int, int]) -> list[str]:
    words = [w for w in _TOKEN.findall(text) if len(w) > 1]
    lo, hi = ngram
    seen: set[str] = set()
    cands: list[str] = []
    for n in range(lo, hi + 1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i : i + n])
            keyed = phrase.casefold()
            if keyed not in seen:
                seen.add(keyed)
                cands.append(phrase)
    return cands


def embedding_keyphrases(
    text: str,
    backend: EmbeddingBackend,
    *,
    top: int = 20,
    ngram: tuple[int, int] = (1, 3),
    diversity: float = 0.5,
) -> list[tuple[str, float]]:
    """KeyBERT-method keyphrases on our embedding backend, MMR-diversified.

    Returns (phrase, cosine-to-document); HIGHER = more relevant.
    """
    cands = _ngram_candidates(text, ngram)
    if not cands:
        return []
    doc_vec = _l2norm(backend.embed([text]))[0]
    cand_vecs = _l2norm(backend.embed(cands))
    doc_sim = cand_vecs @ doc_vec
    selected: list[int] = []
    pool = list(range(len(cands)))
    while pool and len(selected) < top:
        if not selected:
            choice = int(np.argmax(doc_sim))
        else:
            redundancy = (cand_vecs[pool] @ cand_vecs[selected].T).max(axis=1)
            mmr = (1 - diversity) * doc_sim[pool] - diversity * redundancy
            choice = pool[int(np.argmax(mmr))]
        selected.append(choice)
        pool.remove(choice)
    return [(cands[i], float(doc_sim[i])) for i in selected]


def tag_cloud(
    corpus: Corpus, by: str = "tfidf", top: int = 50, min_count: int = 2
) -> list[tuple[str, float]]:
    """Top terms as (surface, weight-normalised-to-1.0), for a tag cloud."""
    cands = corpus.candidates(min_count)
    weigh = (lambda t: t.tfidf) if by == "tfidf" else (lambda t: t.salience)
    ranked = sorted(cands, key=lambda t: -weigh(t))[:top]
    if not ranked:
        return []
    peak = weigh(ranked[0]) or 1.0
    return [(t.surface, weigh(t) / peak) for t in ranked]
