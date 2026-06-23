"""Clustering & themes engine -- group the vocabulary semantically.

KMeans (scikit-learn) over term embeddings, then label each cluster by its
top-salience members. This is the "themes / categorise / topic" view the engine
enables over any corpus -- code symbols or chat history alike. Deterministic
(fixed random_state) so the EDA is reproducible.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from tuparles.nlp.features import Corpus
from tuparles.nlp.signals import EmbeddingBackend, _l2norm


@dataclass
class Cluster:
    cluster_id: int
    label_terms: list[str]  # top-salience members -> the theme, at a glance
    members: list[str]  # all member surfaces (salience desc)
    size: int


def cluster_terms(
    corpus: Corpus,
    backend: EmbeddingBackend,
    *,
    cands: list | None = None,
    n_clusters: int = 8,
    min_count: int = 2,
    label_n: int = 6,
    random_state: int = 0,
) -> list[Cluster]:
    """Embed candidate terms, KMeans them, label by salience. Themes for free.

    Pass an explicit `cands` list to cluster a subset (e.g. the top-distinctive
    terms) instead of the full `corpus.candidates(min_count)`.
    """
    from sklearn.cluster import KMeans

    if cands is None:
        cands = corpus.candidates(min_count)
    if not cands:
        return []
    n_clusters = min(n_clusters, len(cands))
    vecs = _l2norm(backend.embed([t.surface for t in cands]))
    labels = KMeans(
        n_clusters=n_clusters, n_init=10, random_state=random_state
    ).fit_predict(vecs)

    grouped: dict[int, list] = defaultdict(list)
    for term, label in zip(cands, labels, strict=True):
        grouped[int(label)].append(term)

    clusters: list[Cluster] = []
    for cid, members in grouped.items():
        members.sort(key=lambda t: -t.salience)
        surfaces = [m.surface for m in members]
        clusters.append(Cluster(cid, surfaces[:label_n], surfaces, len(members)))
    clusters.sort(key=lambda c: -c.size)
    return clusters
