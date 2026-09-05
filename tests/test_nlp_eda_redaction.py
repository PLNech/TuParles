"""Prevention guard: scripts/nlp_eda.py must never write a raw term surface (or
raw corpus name) mined from a non-public corpus into the metrics JSON -- the
exact incident this guards against was a private work codebase's real
identifiers leaking into public git history through an EDA run (see
docs/research/2026-06-24-codebase-aware-dict-seeding-eda.md).

`nlp_eda.py` is a script, not a package, so it's loaded from disk by path
rather than imported by module name.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tuparles.nlp import Corpus, Document
from tuparles.nlp.parse import SrcType

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nlp_eda.py"


def _load_nlp_eda() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nlp_eda", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses (KW_ONLY resolution) looks the module
    # up in sys.modules while executing it, under `from __future__ import
    # annotations` — a bare module_from_spec() without this raises.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


nlp_eda = _load_nlp_eda()


def _mixed_corpus() -> Corpus:
    """One term from a public repo, one from a private repo -- each seen
    twice so both clear the default min_count=2 candidate filter."""
    c = Corpus()
    c.ingest(
        [
            Document(
                "d1",
                "PublicRepo",
                [("PublicToken", SrcType.DEF_NAME), ("PublicToken", SrcType.IDENT)],
            ),
            Document(
                "d2",
                "SecretRepo",
                [("SecretToken", SrcType.DEF_NAME), ("SecretToken", SrcType.IDENT)],
            ),
        ]
    )
    c.finalize()
    c.compute_metafeatures()
    return c


def test_redactor_leaves_public_surfaces_untouched():
    red = nlp_eda.Redactor(private_repos={"SecretRepo"})
    assert red.surface("PublicToken", "publictoken", _mixed_corpus()) == "PublicToken"


def test_redactor_pseudonymizes_private_surfaces_deterministically():
    c = _mixed_corpus()
    red = nlp_eda.Redactor(private_repos={"SecretRepo"})
    disguised = red.surface("SecretToken", "secrettoken", c)
    assert disguised != "SecretToken"
    assert "SecretToken" not in disguised
    assert "secret" not in disguised.lower()
    # stable across calls/runs -- the redaction must not shuffle every run
    assert disguised == red.surface("SecretToken", "secrettoken", c)


def test_redactor_repo_alias_hides_private_name_but_not_public():
    red = nlp_eda.Redactor(private_repos={"SecretRepo"})
    assert red.repo("PublicRepo") == "PublicRepo"
    alias = red.repo("SecretRepo")
    assert alias != "SecretRepo"
    assert "SecretRepo" not in alias
    assert alias == red.repo("SecretRepo")  # deterministic


def test_no_private_repos_is_a_no_op():
    red = nlp_eda.Redactor(private_repos=set())
    assert red.surface("SecretToken", "secrettoken", _mixed_corpus()) == "SecretToken"
    assert red.repo("SecretRepo") == "SecretRepo"


def test_section_seed_redacts_private_surfaces_in_emitted_json(capsys):
    """End-to-end through the real dict-seed engine: build the report dict the
    way main() does, then check what would actually be written as JSON."""
    c = _mixed_corpus()
    red = nlp_eda.Redactor(private_repos={"SecretRepo"})
    report: dict = {}
    nlp_eda.section_seed(report, c, backend=None, red=red)
    capsys.readouterr()  # drop the printed Markdown table

    dumped = json.dumps(report)
    assert "PublicToken" in dumped
    assert "SecretToken" not in dumped


def test_section_signal_disagreement_redacts_private_surfaces(capsys):
    c = _mixed_corpus()
    red = nlp_eda.Redactor(private_repos={"SecretRepo"})
    report: dict = {}
    nlp_eda.section_signal_disagreement(report, c, red)
    capsys.readouterr()

    dumped = json.dumps(report)
    assert "PublicToken" in dumped
    assert "SecretToken" not in dumped


@pytest.mark.parametrize(
    "value,name,expected_public",
    [
        ("Foo=/tmp/foo", "Foo", False),
        ("Bar=/tmp/bar:public", "Bar", True),
        ("Bar=/tmp/bar:private", "Bar", False),
        ("/tmp/baz", "baz", False),
    ],
)
def test_env_corpora_default_private_unless_marked_public(value, name, expected_public):
    corpora = nlp_eda._parse_env_corpora(value)
    assert corpora[name].public is expected_public


def test_env_corpora_parses_multiple_comma_separated_entries():
    corpora = nlp_eda._parse_env_corpora("Foo=/tmp/foo:public,Bar=/tmp/bar")
    assert corpora["Foo"].public is True
    assert corpora["Bar"].public is False
    assert corpora["Foo"].path == Path("/tmp/foo")
    assert corpora["Bar"].path == Path("/tmp/bar")


def test_builtin_corpora_is_tuparles_public():
    corpora = nlp_eda._builtin_corpora()
    assert corpora["TuParles"].public is True
    assert corpora["TuParles"].path == nlp_eda.REPO_ROOT
