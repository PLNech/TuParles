"""Unit tests for scripts/render_ab_diff.py — on INVENTED fixtures only.

Tiny fake before/after transcripts verify the diff markup, entity badges,
seam styling and fold behaviour without ever touching a real transcript.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load("render_ab_diff")


@pytest.fixture(scope="module")
def scorer():
    return _load("score_transcript_entities")


BEFORE = (
    "# fake.m4a  ·  0:30  ·  small (cpu)  ·  2026-01-01\n"
    "\n"
    "[00:00] Bonjour, on teste Aiku pour la démo du produit.\n"
    "[00:10] La suite est identique dans les deux versions du fichier.\n"
)

AFTER = (
    "# fake.m4a  ·  0:30  ·  small (cpu)  ·  2026-01-02\n"
    "\n"
    "[00:00] Bonjour, on teste Haiku pour la démo du produit.\n"
    "[00:10] — La suite est identique dans les deux versions du fichier.\n"
)


def test_tokenize_separates_structure_from_words(mod):
    toks = mod.tokenize(AFTER)
    kinds = [t.kind for t in toks]
    assert "header" in kinds and "ts" in kinds and "seam" in kinds
    # seam marker and timestamps are NOT diffable words
    assert "—" not in mod.words_of(toks)
    assert all(not t.text.startswith("[") for t in toks if t.kind == "word")


def test_diff_marks_substitution_and_badges(mod, scorer):
    body = mod.render_pair_body(BEFORE, AFTER, scorer.ENTITY_SPEC)
    # the removed wrong form: struck through AND badged as known-wrong
    assert '"del pill-bad">Aiku</span>' in body
    # the added correct form: inserted AND badged as correct
    assert '"ins pill-ok">Haiku</span>' in body
    # unchanged words render dimmed, inside no hunk
    assert '<span class="eq">Bonjour,</span>' in body


def test_seam_renders_with_affordance(mod, scorer):
    body = mod.render_pair_body(BEFORE, AFTER, scorer.ENTITY_SPEC)
    assert body.count('class="seam"') == 1
    assert "tour?" in body


def test_long_unchanged_run_folds(mod, scorer):
    filler = " ".join(f"mot{i}" for i in range(80))
    before = f"[00:00] début {filler} fin.\n"
    after = f"[00:00] commencement {filler} fin.\n"
    body = mod.render_pair_body(before, after, scorer.ENTITY_SPEC)
    assert "mots inchangés" in body
    assert 'class="fold"' in body
    # the changed word is in a hunk and never folded
    assert "commencement" in body and "début" in body


def test_short_texts_do_not_fold(mod, scorer):
    body = mod.render_pair_body(BEFORE, AFTER, scorer.ENTITY_SPEC)
    assert "mots inchangés" not in body


def test_stat_strip_counts_only(mod, scorer):
    strip = mod.stat_strip(BEFORE, AFTER, scorer.ENTITY_SPEC)
    # correct forms went 0 -> 1, wrong forms 1 -> 0
    assert "entités correctes : 0 → 1" in strip
    assert "formes fautives : 1 → 0" in strip
    assert "tours détectés : 1" in strip
    # no transcript prose leaks into the stat strip
    assert "Bonjour" not in strip


def test_full_page_is_self_contained(mod, scorer, tmp_path):
    b = tmp_path / "b.txt"
    a = tmp_path / "a.txt"
    b.write_text(BEFORE, encoding="utf-8")
    a.write_text(AFTER, encoding="utf-8")
    page = mod.render_page([(b, a)], scorer.ENTITY_SPEC, chart=None)
    assert page.startswith("<!doctype html>")
    assert "TuParles — avant/après" in page
    # zero external references: no http(s) URLs, scripts or stylesheets
    assert "http://" not in page and "https://" not in page
    assert "<link" not in page
    # nav anchor for the file pair
    assert 'href="#f1"' in page and "b.txt" in page


def test_cli_writes_output(mod, tmp_path, capsys):
    b = tmp_path / "b.txt"
    a = tmp_path / "a.txt"
    out = tmp_path / "out" / "diff.html"
    b.write_text(BEFORE, encoding="utf-8")
    a.write_text(AFTER, encoding="utf-8")
    rc = mod.main(["--pair", str(b), str(a), "-o", str(out)])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 1000
