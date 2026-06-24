"""Corpus-analysis core (nlp/) — pure-logic + light-dep tests.

The embedding-backed paths (fastembed / clustering / KeyBERT-method) are marked
`embed` and deselected by default; run them with `pytest -m embed` after
`poetry install --with embed`. Everything here needs only the portable `nlp`
group (markdown-it-py / scikit-learn / yake).
"""

import pytest

from tuparles.nlp import Corpus, Document, message_documents, text_documents
from tuparles.nlp.crawl import Kind, classify
from tuparles.nlp.engines import dictseed, keywords
from tuparles.nlp.features import TermStats
from tuparles.nlp.fuse import rrf, rrf_contributions
from tuparles.nlp.parse import (
    SrcType,
    parse_manifest,
    parse_markdown,
    parse_python,
)


def _doc(terms, doc_id="d", source="s"):
    return Document(doc_id, source, terms)


# --------------------------------------------------------------------------- #
# crawl                                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path,kind",
    [
        ("a/b.py", Kind.PYTHON),
        ("README.md", Kind.MARKDOWN),
        ("pyproject.toml", Kind.MANIFEST),
        ("package.json", Kind.MANIFEST),
        ("requirements.txt", Kind.MANIFEST),
        ("src/x.cpp", Kind.CODE),
        ("src/x.h", Kind.CODE),
        ("data.json", Kind.DATA),
        ("out.log", Kind.NOISE),
        ("img.png", Kind.NOISE),
    ],
)
def test_classify(path, kind):
    assert classify(path) is kind


# --------------------------------------------------------------------------- #
# parse: Python AST                                                            #
# --------------------------------------------------------------------------- #
def test_parse_python_defs_imports_doc_comment():
    src = (
        '"""Module doc word."""\n'
        "import os\n"
        "from a.b import c\n"
        "class Foo:\n"
        '    "klass doc"\n'
        "    def bar(self):\n"
        "        x = 1  # commentword\n"
        "        return x\n"
    )
    pairs = list(parse_python(src))
    assert ("Foo", SrcType.DEF_NAME) in pairs
    assert ("bar", SrcType.DEF_NAME) in pairs
    assert ("os", SrcType.IMPORT) in pairs
    assert ("a", SrcType.IMPORT) in pairs  # from a.b -> top package
    assert any(st is SrcType.DOCSTRING for _, st in pairs)
    assert ("commentword", SrcType.COMMENT) in pairs


def test_parse_python_syntax_error_is_empty():
    assert list(parse_python("def (:::")) == []


# --------------------------------------------------------------------------- #
# parse: Markdown hierarchy                                                    #
# --------------------------------------------------------------------------- #
def test_parse_markdown_headings_and_code():
    md = (
        "# Title here\n"
        "some prose `inlineCode` here\n\n"
        "## Subsection\n\n"
        "```\nfenced_ident = 1\n```\n"
    )
    pairs = list(parse_markdown(md))
    assert ("Title", SrcType.MD_H1) in pairs
    assert ("Subsection", SrcType.MD_H2) in pairs
    assert ("inlineCode", SrcType.MD_CODE_INLINE) in pairs
    assert ("fenced_ident", SrcType.MD_CODE_FENCE) in pairs
    assert ("prose", SrcType.MD_PROSE) in pairs


# --------------------------------------------------------------------------- #
# parse: manifests (dep names = top weight)                                    #
# --------------------------------------------------------------------------- #
def test_parse_manifest_pyproject():
    toml = (
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        'numpy = "^2.0"\n'
        "[project]\n"
        'dependencies = ["requests>=2"]\n'
    )
    deps = {t for t, st in parse_manifest(toml, "pyproject.toml") if st is SrcType.DEP}
    assert "numpy" in deps and "requests" in deps and "python" not in deps


def test_parse_manifest_package_json():
    js = '{"dependencies":{"react":"^18"},"devDependencies":{"jest":"^29"}}'
    assert {t for t, _ in parse_manifest(js, "package.json")} == {"react", "jest"}


def test_parse_manifest_requirements():
    req = "# a comment\nrequests==2.0\nnumpy>=1.0\n"
    assert {t for t, _ in parse_manifest(req, "requirements.txt")} == {
        "requests",
        "numpy",
    }


# --------------------------------------------------------------------------- #
# features: aggregation, flags, tfidf                                          #
# --------------------------------------------------------------------------- #
def test_corpus_aggregates_and_flags():
    c = Corpus()
    c.ingest(
        [
            _doc(
                [
                    ("getFacetValues", SrcType.DEF_NAME),
                    ("API_KEY", SrcType.IDENT),
                    ("hello", SrcType.MD_PROSE),
                ],
                "d1",
            ),
            _doc(
                [("getFacetValues", SrcType.IDENT), ("café", SrcType.MD_PROSE)],
                "d2",
            ),
        ]
    )
    c.finalize()
    g = c.stats["getfacetvalues"]
    assert g.count == 2 and g.doc_freq == 2 and g.is_camel and g.is_identifier
    assert g.salience == 6.0 + 3.0  # DEF_NAME + IDENT
    assert c.stats["api_key"].is_acronym and c.stats["api_key"].is_snake
    assert c.stats["café"].has_accent


def test_compute_metafeatures_tfidf_rewards_rarity():
    c = Corpus()
    c.ingest(
        [
            _doc([("common", SrcType.TEXT), ("rare", SrcType.TEXT)], "d1"),
            _doc([("common", SrcType.TEXT)], "d2"),
            _doc([("common", SrcType.TEXT)], "d3"),
        ]
    )
    c.finalize()
    c.compute_metafeatures()
    # 'rare' (1 doc) is more distinctive than 'common' (every doc)
    assert c.stats["rare"].tfidf > c.stats["common"].tfidf


def test_candidates_min_count():
    c = Corpus()
    c.ingest(
        [_doc([("seen", SrcType.TEXT), ("seen", SrcType.TEXT), ("once", SrcType.TEXT)])]
    )
    c.finalize()
    keys = {t.key for t in c.candidates(min_count=2)}
    assert keys == {"seen"}


# --------------------------------------------------------------------------- #
# fuse: RRF                                                                    #
# --------------------------------------------------------------------------- #
def test_rrf_rewards_agreement():
    fused = rrf({"a": ["x", "y", "z"], "b": ["x", "z", "y"]})
    assert fused[0][0] == "x"


def test_rrf_contributions():
    contrib = rrf_contributions({"a": ["x", "y"]}, "y")
    assert contrib["a"] == pytest.approx(1 / (60 + 2))
    assert rrf_contributions({"a": ["x"]}, "absent")["a"] == 0.0


# --------------------------------------------------------------------------- #
# engine: dict-seed                                                            #
# --------------------------------------------------------------------------- #
def test_whisper_risk_code_beats_prose():
    code = TermStats(
        key="g", surface="getFacetValues", is_camel=True, is_identifier=True
    )
    prose = TermStats(key="b", surface="bonjour")
    assert dictseed.whisper_risk(code) > dictseed.whisper_risk(prose)


def test_seed_prefers_code_shaped_terms():
    c = Corpus()
    c.ingest(
        [
            _doc(
                [("getFacetValues", SrcType.DEF_NAME), ("bonjour", SrcType.MD_H1)],
                "d1",
            ),
            _doc(
                [("getFacetValues", SrcType.IDENT), ("bonjour", SrcType.MD_PROSE)],
                "d2",
            ),
        ]
    )
    c.finalize()
    c.compute_metafeatures()
    seeds = {s.key: s for s in dictseed.seed(c, min_count=2)}
    assert seeds["getfacetvalues"].seed_score > seeds["bonjour"].seed_score
    assert seeds["getfacetvalues"].signals  # per-signal contributions populated


# --------------------------------------------------------------------------- #
# engine: keywords / tag cloud                                                 #
# --------------------------------------------------------------------------- #
def test_tag_cloud_normalised_to_one():
    c = Corpus()
    c.ingest(
        [
            _doc(
                [("alpha", SrcType.DEF_NAME)] * 3 + [("beta", SrcType.MD_PROSE)], "d1"
            ),
            _doc([("alpha", SrcType.IDENT)], "d2"),
        ]
    )
    c.finalize()
    c.compute_metafeatures()
    cloud = keywords.tag_cloud(c, by="salience", top=5, min_count=1)
    assert cloud[0][1] == 1.0
    assert all(0 < w <= 1.0 for _, w in cloud)


def test_yake_keyphrases_runs():
    kps = keywords.yake_keyphrases(
        "Local push to talk dictation for French English code switchers", top=5
    )
    assert kps and all(isinstance(p, str) and isinstance(s, float) for p, s in kps)


# --------------------------------------------------------------------------- #
# sources: the modular non-code path (chat history / logs / transcripts)       #
# --------------------------------------------------------------------------- #
def test_message_documents_mines_prose():
    c = Corpus()
    c.ingest(
        message_documents(
            [(1, "fanout les agents avec RequestOptions"), (2, "le faceting est cassé")]
        )
    )
    c.finalize()
    assert "faceting" in c.stats and "requestoptions" in c.stats
    assert c.stats["faceting"].by_type["text"] >= 1


def test_text_documents_reads_files(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("keyword world keyword", encoding="utf-8")
    c = Corpus()
    c.ingest(text_documents([p], source="notes"))
    c.finalize()
    assert c.stats["keyword"].count == 2
    assert c.stats["keyword"].repo_freq == 1


# --------------------------------------------------------------------------- #
# embedding-backed paths (optional `embed` group) — deselected by default       #
# --------------------------------------------------------------------------- #
@pytest.mark.embed
def test_fastembed_rank_and_cluster():
    from tuparles.nlp.engines import cluster
    from tuparles.nlp.signals import FastEmbedBackend, rank_embed

    c = Corpus()
    c.ingest(
        [
            _doc(
                [
                    ("faceting", SrcType.DEF_NAME),
                    ("relevance", SrcType.DEF_NAME),
                    ("banana", SrcType.MD_PROSE),
                ],
                "d1",
            ),
            _doc([("faceting", SrcType.IDENT)], "d2"),
        ]
    )
    c.finalize()
    backend = FastEmbedBackend()
    cands = c.candidates(min_count=1)
    ranked, vecs = rank_embed(cands, backend)
    assert len(ranked) == len(cands) and vecs.shape[0] == len(cands)
    clusters = cluster.cluster_terms(c, backend, n_clusters=2, min_count=1)
    assert sum(cl.size for cl in clusters) == len(cands)


@pytest.mark.embed
def test_embedding_keyphrases():
    from tuparles.nlp.signals import FastEmbedBackend

    phrases = keywords.embedding_keyphrases(
        "faceting and relevance tuning for search ranking",
        FastEmbedBackend(),
        top=5,
    )
    assert phrases and all(isinstance(p, str) for p, _ in phrases)
