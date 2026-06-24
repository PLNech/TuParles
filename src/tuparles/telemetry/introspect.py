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

    The corpus is built from already-redacted history (block-tier PII was
    stripped at persist, #115), so the only PII risk left is a rarely-spoken
    name. `pii_analytics_min_count` is the k-floor against that: default 1
    keeps short clouds non-empty; raise it for k-anonymity over one-off terms.
    """
    if not nlp_available():
        return []
    corpus = _utterance_corpus(limit)
    if corpus is None:
        return []
    from tuparles import privacy_policy
    from tuparles.nlp.engines import keywords

    return keywords.tag_cloud(
        corpus, by="tfidf", top=top, min_count=privacy_policy.analytics_min_count()
    )


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
    """The telemetry view: per-feature counts and the entry-path split.

    Counts are by the feature's own name (the `name`/`source` attr), not the
    coarse event name — "undo fired 4×", not "command.fired fired 4×". Pure
    stdlib + sqlite, so it works with or without the nlp extras.
    """
    return {
        "total": sum(readout.usage_counts().values()),
        "commands": dict(readout.attr_split("command.fired", "name")),
        "syntax_used": dict(readout.attr_split("syntax.used", "name")),
        "entry_split": dict(readout.attr_split("entry.dictation", "source")),
    }


def corpus_analysis() -> dict | None:
    """The last cached codebase EDA — instant and freeze-free.

    Computing a corpus live on dialog-open would do a multi-second discovery +
    TF-IDF build on the GUI thread (the stall watchdog would scream), and
    "which project?" needs active-project detect (#70, unbuilt). So the corpus
    view renders the JSON `scripts/nlp_eda.py` already writes, labelled with
    its date + repos. A worker-thread refresh is a clean fast-follow. None when
    no analysis has been run yet.
    """
    import json
    from pathlib import Path

    # parents[3] = repo root (telemetry → tuparles → src → root); assumes a dev
    # checkout. A non-editable install has no docs/ → None → "Aucune analyse".
    data_dir = Path(__file__).resolve().parents[3] / "docs" / "research" / "data"
    cached = sorted(data_dir.glob("*-nlp-eda.json")) if data_dir.is_dir() else []
    if not cached:
        return None
    try:
        return json.loads(cached[-1].read_text())
    except (OSError, ValueError):
        return None
