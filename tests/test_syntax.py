"""Unit tests for the spoken-syntax core (#57) — pure logic, no GPU, no audio.

The core is the framework every family trusts; pin its mechanics before any
family ships.
"""

import pytest

from tuparles import syntax
from tuparles.syntax import SyntaxContext, SyntaxFeature, apply_syntax


@pytest.fixture(autouse=True)
def _clean_registry():
    syntax.clear()
    yield
    syntax.clear()


def _recorder(name, log, mark=None, order=100, default=True):
    """A feature that appends its name to `log` and optionally tags the text."""
    def fn(text, ctx):
        log.append(name)
        return f"{text}|{mark}" if mark else text
    return SyntaxFeature(name=name, apply=fn, default_enabled=default, order=order)


def test_context_defaults_to_plain():
    ctx = SyntaxContext()
    assert ctx.fmt == "plain"
    assert ctx.app_class is None


def test_empty_registry_is_identity():
    assert apply_syntax("hello world") == "hello world"


def test_features_run_in_declared_order():
    log = []
    syntax.register(_recorder("late", log, order=200))
    syntax.register(_recorder("early", log, order=10))
    apply_syntax("x")
    assert log == ["early", "late"]


def test_registered_lists_names_in_order():
    log = []
    syntax.register(_recorder("b", log, order=20))
    syntax.register(_recorder("a", log, order=10))
    assert syntax.registered() == ["a", "b"]


def test_register_replaces_by_name():
    log = []
    syntax.register(_recorder("dup", log, mark="v1"))
    syntax.register(_recorder("dup", log, mark="v2"))
    assert syntax.registered() == ["dup"]
    assert apply_syntax("t") == "t|v2"


def test_disabled_feature_is_skipped(monkeypatch):
    log = []
    syntax.register(_recorder("quotes", log))
    monkeypatch.setattr(syntax.settings, "get", lambda key: {"quotes": False})
    apply_syntax("x")
    assert log == []


def test_settings_absent_uses_feature_default(monkeypatch):
    log = []
    syntax.register(_recorder("on_by_default", log, default=True))
    syntax.register(_recorder("off_by_default", log, default=False))
    monkeypatch.setattr(syntax.settings, "get", lambda key: None)
    apply_syntax("x")
    assert log == ["on_by_default"]


def test_settings_override_beats_default(monkeypatch):
    log = []
    syntax.register(_recorder("off_by_default", log, default=False))
    monkeypatch.setattr(syntax.settings, "get", lambda key: {"off_by_default": True})
    apply_syntax("x")
    assert log == ["off_by_default"]


def test_malformed_settings_falls_back_to_default(monkeypatch):
    log = []
    syntax.register(_recorder("f", log, default=True))
    monkeypatch.setattr(syntax.settings, "get", lambda key: "not a dict")
    apply_syntax("x")
    assert log == ["f"]


def test_context_is_threaded_to_features():
    seen = {}
    syntax.register(SyntaxFeature(
        name="peek",
        apply=lambda text, ctx: seen.update(fmt=ctx.fmt) or text,
    ))
    apply_syntax("x", SyntaxContext(fmt="markdown"))
    assert seen["fmt"] == "markdown"


def test_a_failing_feature_never_crashes_the_take(capsys):
    def boom(text, ctx):
        raise ValueError("kaboom")

    log = []
    syntax.register(SyntaxFeature(name="boom", apply=boom, order=10))
    syntax.register(_recorder("after", log, order=20))
    # the take survives, later features still run, the slip is logged
    assert apply_syntax("kept") == "kept"
    assert log == ["after"]
    assert "boom" in capsys.readouterr().out


def test_transformations_chain_left_to_right():
    log = []
    syntax.register(_recorder("first", log, mark="A", order=10))
    syntax.register(_recorder("second", log, mark="B", order=20))
    assert apply_syntax("t") == "t|A|B"
