"""Corpus-analysis core for TuParles.

A small, source-agnostic pipeline:

    sources (code / text / chat)  ->  Document stream
    Corpus.ingest                 ->  per-term features (count, salience, ...)
    Corpus.compute_metafeatures   ->  TF-IDF (scikit-learn)
    signals + fuse                ->  ranked, RRF-fused views
    engines.{dictseed,keywords,cluster}  ->  applications

We own the thin spine (the typed-term Document, the AST extraction) because no
library models code symbols *and* their structural provenance; we rent the
algorithms (TF-IDF, clustering, keyphrases) from scikit-learn / YAKE / fastembed.

Heavy/optional imports (sklearn, yake, embedding backends) stay lazy, so
importing this package is cheap. Engines live under `tuparles.nlp.engines`.
"""

from tuparles.nlp.features import Corpus, TermStats
from tuparles.nlp.sources import (
    DiscoveryStats,
    Document,
    code_documents,
    message_documents,
    text_documents,
)

__all__ = [
    "Corpus",
    "DiscoveryStats",
    "Document",
    "TermStats",
    "code_documents",
    "message_documents",
    "text_documents",
]
