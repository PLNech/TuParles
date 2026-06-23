"""Spoken-quotes family (#32) — pure logic, no GPU.

Tests call `quotes.apply` directly with a SyntaxContext, controlling marks via a
patched settings.get. Default marks are straight " for both languages.
"""

from tuparles.syntax import SyntaxContext
from tuparles.syntax_features import quotes

CTX = SyntaxContext()


def _cfg(monkeypatch, conf=None):
    """Patch the 'quotes' settings the feature reads (None → defaults)."""
    monkeypatch.setattr(
        quotes.settings, "get", lambda key: conf if key == "quotes" else None
    )


def test_no_triggers_is_identity(monkeypatch):
    _cfg(monkeypatch)
    assert quotes.apply("juste du texte normal", CTX) == "juste du texte normal"


def test_explicit_fr_open_close(monkeypatch):
    _cfg(monkeypatch)
    assert quotes.apply("ouvre les guillemets bonjour ferme les guillemets", CTX) == (
        '"bonjour"'
    )


def test_explicit_en_open_close(monkeypatch):
    _cfg(monkeypatch)
    assert quotes.apply("open quote hello close quote", CTX) == '"hello"'


def test_en_unquote_closes(monkeypatch):
    _cfg(monkeypatch)
    assert quotes.apply("open quote hello unquote", CTX) == '"hello"'


def test_bare_pair_is_quotes(monkeypatch):
    _cfg(monkeypatch)
    assert quotes.apply("guillemets bonjour guillemets", CTX) == '"bonjour"'


def test_lone_bare_guillemets_stays_text(monkeypatch):
    # the structural guard: one bare 'guillemets' is the word, not a quote
    _cfg(monkeypatch)
    text = "les guillemets sont importants en typographie"
    assert quotes.apply(text, CTX) == text


def test_entre_guillemets_opens_and_auto_closes(monkeypatch):
    _cfg(monkeypatch)
    assert quotes.apply("entre guillemets important", CTX) == '"important"'


def test_auto_close_on_unclosed_open(monkeypatch):
    _cfg(monkeypatch)
    assert quotes.apply("open quote hello", CTX) == '"hello"'


def test_auto_close_disabled(monkeypatch):
    _cfg(monkeypatch, {"auto_close": False})
    assert quotes.apply("open quote hello", CTX) == '"hello'


def test_guillemets_narrow_spacing(monkeypatch):
    _cfg(monkeypatch, {"fr": "guillemets-narrow"})
    # « + U+202F + bonjour + U+202F + »
    assert quotes.apply("guillemets bonjour guillemets", CTX) == ("« bonjour »")


def test_guillemets_none_spacing(monkeypatch):
    _cfg(monkeypatch, {"fr": "guillemets-none"})
    assert quotes.apply("guillemets bonjour guillemets", CTX) == "«bonjour»"


def test_guillemets_full_spacing(monkeypatch):
    _cfg(monkeypatch, {"fr": "guillemets-full"})
    assert quotes.apply("guillemets bonjour guillemets", CTX) == ("« bonjour »")


def test_en_curly(monkeypatch):
    _cfg(monkeypatch, {"en": "curly"})
    assert quotes.apply("open quote hello close quote", CTX) == "“hello”"


def test_en_context_prose_is_curly(monkeypatch):
    _cfg(monkeypatch, {"en": "context"})
    assert quotes.apply("open quote hi close quote", SyntaxContext()) == ("“hi”")


def test_en_context_in_terminal_is_straight(monkeypatch):
    _cfg(monkeypatch, {"en": "context"})
    ctx = SyntaxContext(app_class="org.gnome.Console")
    assert quotes.apply("open quote ls close quote", ctx) == '"ls"'


def test_leaves_no_sentinels(monkeypatch):
    _cfg(monkeypatch)
    out = quotes.apply("guillemets a guillemets et open quote b close quote", CTX)
    assert "\x00" not in out


def test_nested_pair_alternates(monkeypatch):
    # four bare = open, close, open, close → two adjacent quoted words
    _cfg(monkeypatch)
    assert quotes.apply("guillemets a guillemets guillemets b guillemets", CTX) == (
        '"a" "b"'
    )
