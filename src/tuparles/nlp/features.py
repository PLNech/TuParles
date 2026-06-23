"""Aggregate typed term occurrences into per-term features.

These are the *generic*, application-agnostic features -- counts, document and
repo frequency, summed hierarchical salience, the SrcType breakdown, and a few
orthographic flags. TF-IDF is rented from scikit-learn (its idf smoothing and
sublinear-tf are battle-tested; no point hand-rolling them).

Anything application-specific -- the dictation `whisper_risk`/`seed_score`, the
keyword phrases, the clusters -- lives in `nlp.engines.*`, computed *from* these
features. Keep this module about "what is in the corpus", not "what to do with it".
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

from tuparles.nlp.parse import IDENTIFIER_TYPES, WEIGHT
from tuparles.nlp.sources import Document

_CAMEL = re.compile(r"[a-z][A-Z]|[A-Z]{2}[a-z]")
_HAS_DIGIT = re.compile(r"\d")
_ALPHA = re.compile(r"[A-Za-zÀ-ſ]")


@dataclass
class TermStats:
    key: str  # casefolded aggregation key
    surface: str  # most common original surface form
    count: int = 0
    doc_freq: int = 0
    repo_freq: int = 0
    salience: float = 0.0  # Σ hierarchical weight over all occurrences
    by_type: Counter = field(default_factory=Counter)
    # orthographic flags (filled by finalize)
    is_camel: bool = False
    is_snake: bool = False
    is_acronym: bool = False
    has_digit: bool = False
    is_identifier: bool = False  # ever seen as a code identifier
    has_accent: bool = False
    # generic metafeature (filled by compute_metafeatures)
    tfidf: float = 0.0  # peak TF-IDF across documents (corpus distinctiveness)


class Corpus:
    """Ingest Documents, hold the term table + the doc-term matrix for TF-IDF."""

    def __init__(self) -> None:
        self.stats: dict[str, TermStats] = {}
        self._surface_votes: dict[str, Counter] = {}
        self._files: dict[str, set[str]] = {}  # key -> doc ids
        self._repos: dict[str, set[str]] = {}  # key -> source names
        self.doc_terms: list[Counter] = []  # per-document casefold term counts
        self.n_docs = 0

    def ingest(self, documents: Iterable[Document]) -> None:
        for doc in documents:
            bag: Counter = Counter()
            for term, srctype in doc.terms:
                key = term.casefold()
                if len(key) < 2:
                    continue
                ts = self.stats.get(key)
                if ts is None:
                    ts = TermStats(key=key, surface=term)
                    self.stats[key] = ts
                    self._surface_votes[key] = Counter()
                    self._files[key] = set()
                    self._repos[key] = set()
                ts.count += 1
                ts.salience += WEIGHT[srctype]
                ts.by_type[srctype.value] += 1
                if srctype in IDENTIFIER_TYPES:
                    ts.is_identifier = True
                self._surface_votes[key][term] += 1
                self._files[key].add(doc.doc_id)
                self._repos[key].add(doc.source)
                bag[key] += 1
            if bag:
                self.doc_terms.append(bag)
                self.n_docs += 1

    def finalize(self) -> None:
        """Resolve surface forms, file/repo frequencies, orthographic flags."""
        for key, ts in self.stats.items():
            ts.surface = self._surface_votes[key].most_common(1)[0][0]
            ts.doc_freq = len(self._files[key])
            ts.repo_freq = len(self._repos[key])
            s = ts.surface
            ts.is_camel = bool(_CAMEL.search(s))
            ts.is_snake = "_" in s and s.strip("_") != ""
            ts.is_acronym = len(s) >= 2 and s.isupper() and bool(_ALPHA.search(s))
            ts.has_digit = bool(_HAS_DIGIT.search(s))
            ts.has_accent = s != s.encode("ascii", "ignore").decode()

    def compute_metafeatures(self) -> None:
        """Peak per-term TF-IDF across documents, via scikit-learn (rented)."""
        if not self.doc_terms:
            return
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.feature_extraction.text import TfidfTransformer

        dv = DictVectorizer(dtype=np.float64)
        counts = dv.fit_transform([dict(d) for d in self.doc_terms])
        # norm=None: keep raw tf·idf so peak reflects "frequent here AND rare
        # across the corpus", not an artefact of a term being alone in a doc
        # (l2 would push any lone-term doc to 1.0).
        tfidf = (
            TfidfTransformer(sublinear_tf=True, norm=None)
            .fit_transform(counts)
            .tocsc()
        )
        names = dv.get_feature_names_out()
        for j, key in enumerate(names):
            col = tfidf.getcol(j).data
            ts = self.stats.get(str(key))
            if ts is not None:
                ts.tfidf = float(col.max()) if col.size else 0.0

    def candidates(self, min_count: int = 2) -> list[TermStats]:
        """Terms worth ranking: seen more than once (drop one-off noise/typos)."""
        return [t for t in self.stats.values() if t.count >= min_count]
