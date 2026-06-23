"""Three ranked views of the candidate vocabulary, to be fused by RRF.

Each signal answers "which terms matter?" from a different angle:

* **symbol**  -- structural salience (Σ hierarchical weight). A dep name or an
  H1 outranks a comment word. Cheap, deterministic, no model.
* **tfidf**   -- corpus distinctiveness (peak TF-IDF, via scikit-learn). Down-
  weights words that are everywhere; surfaces what characterises *this* code.
* **embed**   -- semantic domain-centrality: embed each term, rank by cosine to
  the salience-weighted corpus centroid. Surfaces the jargon cluster a lexical
  signal can miss. Backend is pluggable (fastembed now; sentence-transformers
  drops in post-reboot) so we can *compare* what each model surfaces (#66).

RRF (fuse.py) needs only the ranked key lists, so each signal returns one.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from tuparles.nlp.features import TermStats


def rank_symbol(cands: Sequence[TermStats]) -> list[str]:
    return [t.key for t in sorted(cands, key=lambda t: -t.salience)]


def rank_tfidf(cands: Sequence[TermStats]) -> list[str]:
    return [t.key for t in sorted(cands, key=lambda t: -t.tfidf)]


# --------------------------------------------------------------------------- #
# Embedding backends -- one interface, several models, so we can compare them. #
# --------------------------------------------------------------------------- #
class EmbeddingBackend:
    """Embed a list of strings -> (n, d) float array. One method to implement."""

    name = "base"

    def embed(self, texts: list[str]) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError


class FastEmbedBackend(EmbeddingBackend):
    """ONNX, CPU-native, no torch -- the lean backend we'd actually ship."""

    def __init__(
        self, model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ) -> None:
        from fastembed import TextEmbedding

        self.name = f"fastembed:{model.split('/')[-1]}"
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(list(self._model.embed(texts)), dtype=np.float32)


class SentenceTransformerBackend(EmbeddingBackend):
    """The familiar baseline. Needs a torch that imports on this box -- deferred
    to a post-reboot session with a matched (CPU or CUDA) torch."""

    def __init__(self, model: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self.name = f"st:{model}"
        self._model = SentenceTransformer(model)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            self._model.encode(texts, normalize_embeddings=False), dtype=np.float32
        )


def rank_embed(
    cands: Sequence[TermStats], backend: EmbeddingBackend
) -> tuple[list[str], np.ndarray]:
    """Rank candidates by cosine to the salience-weighted corpus centroid.

    Returns (ranked_keys, embeddings) -- embeddings handed back so the EDA can
    reuse them (clustering, neighbour inspection) without re-encoding.
    """
    keys = [t.key for t in cands]
    vecs = backend.embed([t.surface for t in cands])
    vecs = _l2norm(vecs)
    weights = np.array([max(t.salience, 1e-6) for t in cands], dtype=np.float32)
    centroid = _l2norm((vecs * weights[:, None]).sum(axis=0, keepdims=True))[0]
    sims = vecs @ centroid
    order = np.argsort(-sims)
    return [keys[i] for i in order], vecs


def _l2norm(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.clip(n, 1e-12, None)
