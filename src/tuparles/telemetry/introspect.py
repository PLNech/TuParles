"""Bridge: run the nlp engine over local introspection data.

Utterances (what you dictated) flow through the same source-agnostic nlp
pipeline the codebase uses — `message_documents` — so the Analytics dashboard
(#101) can show a tag cloud and keyphrases over your own voice. The event log
(what you *did*) is structured, so its "analysis" is the readout aggregations,
not nlp. Both stay 100% local.

The nlp extras (scikit-learn, yake) are a default-installed group but can be
left out (`poetry install --without nlp`); every nlp-backed function degrades
to an empty result rather than raising, and the dashboard says why.
"""

from __future__ import annotations

from tuparles import history
from tuparles.telemetry import readout


def nlp_available() -> bool:
    """True when the nlp extras are importable — the dashboard gates on this."""
    try:
        import sklearn  # noqa: F401
        import yake  # noqa: F401
    except ImportError:
        return False
    return True


def _utterance_corpus(limit: int):
    from tuparles.nlp import Corpus, message_documents

    texts = history.texts(limit)
    if not texts:
        return None
    corpus = Corpus()
    corpus.ingest(message_documents(enumerate(texts)))
    corpus.finalize()
    corpus.compute_metafeatures()
    return corpus


def utterance_tags(limit: int = 2000, top: int = 50) -> list[tuple[str, float]]:
    """Tag cloud over recent dictations — the words you actually speak.

    min_count=1: dictations are short, so a count≥2 gate would empty the cloud.
    """
    if not nlp_available():
        return []
    corpus = _utterance_corpus(limit)
    if corpus is None:
        return []
    from tuparles.nlp.engines import keywords

    return keywords.tag_cloud(corpus, by="tfidf", top=top, min_count=1)


def utterance_keyphrases(
    limit: int = 2000, top: int = 20, lang: str = "fr"
) -> list[tuple[str, float]]:
    """YAKE keyphrases over the joined dictation history (lower score = better)."""
    if not nlp_available():
        return []
    texts = history.texts(limit)
    if not texts:
        return []
    from tuparles.nlp.engines import keywords

    return keywords.yake_keyphrases("\n".join(texts), lang=lang, top=top)


def usage_summary() -> dict:
    """The telemetry view: counts, the discovery gap, and the entry-path split.

    Pure stdlib + sqlite, so it works with or without the nlp extras.
    """
    return {
        "total": sum(readout.usage_counts().values()),
        "commands": dict(readout.usage_counts(prefix="command.")),
        "syntax": dict(readout.usage_counts(prefix="syntax.")),
        "entry_split": dict(readout.attr_split("entry.dictation", "source")),
    }
