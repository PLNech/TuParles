"""Re-case engine (#120). Pure, no-GPU. The doctrine under test: preserve is the
default identity, the conservative guards never re-case non-prose, and (until
#122) lower honestly lowercases proper nouns."""

from tuparles import casing


class TestPreserve:
    def test_default_is_identity(self):
        text = "Bonjour, I shipped the API to prod. iPhone."
        assert casing.recase(text) == text

    def test_unknown_style_is_identity(self):
        text = "Whatever Style."
        assert casing.recase(text, "kebab") == text

    def test_empty_string(self):
        assert casing.recase("", "lower") == ""


class TestLower:
    def test_lowercases_prose(self):
        assert casing.recase("Bonjour Le Monde", "lower") == "bonjour le monde"

    def test_preserves_whitespace_exactly(self):
        assert casing.recase("A  B\tC\n", "lower") == "a  b\tc\n"

    def test_protects_all_caps_acronym(self):
        assert casing.recase("the API and GPU", "lower") == "the API and GPU"

    def test_protects_urls_emails_handles(self):
        src = "ping https://x.io or me@host.com or @paul"
        assert casing.recase(src, "lower") == src

    def test_protects_identifiers(self):
        # camelCase, snake_case, digit-bearing, internal caps.
        for tok in ("iPhone", "snake_case", "h264", "GitHub", "v2"):
            assert casing.recase(tok, "lower") == tok

    def test_lowercases_proper_nouns_documented_gap(self):
        # The honest #122 gap: lowkey lowercase eats proper nouns. Opt-in, not a bug.
        assert casing.recase("I met Marie in Paris", "lower") == "i met marie in paris"

    def test_lowercases_plural_acronym_documented_gap(self):
        # str.isupper() is False on "APIs", so the acronym guard misses it.
        assert casing.recase("two APIs and IDs", "lower") == "two apis and ids"

    def test_single_letter_not_protected(self):
        assert casing.recase("I A B", "lower") == "i a b"

    def test_keeps_punctuation(self):
        assert casing.recase("Hello, World!", "lower") == "hello, world!"


class TestSentence:
    def test_capitalizes_sentence_starts(self):
        assert casing.recase("hello. how are you?", "sentence") == "Hello. How are you?"

    def test_does_not_downcase_the_middle(self):
        # Up-casing only: a mid-sentence proper noun / acronym survives untouched.
        src = "we love Paris and the API a lot."
        assert casing.recase(src, "sentence") == "We love Paris and the API a lot."

    def test_protects_identifier_at_sentence_start(self):
        # Never turn "iPhone is great" into "IPhone is great".
        assert casing.recase("iPhone is great.", "sentence") == "iPhone is great."

    def test_leading_bracket_then_word(self):
        assert casing.recase("(hello) world.", "sentence") == "(Hello) world."

    def test_closing_quote_after_terminator(self):
        out = casing.recase('he said "go." then left.', "sentence")
        assert out == 'He said "go." then left.'


class TestUpper:
    def test_uppercases_prose(self):
        assert casing.recase("hello world", "upper") == "HELLO WORLD"

    def test_protects_url(self):
        src = "go to https://x.io now"
        assert casing.recase(src, "upper") == "GO TO https://x.io NOW"


class TestUnicode:
    def test_ligature_lowercases(self):
        # œ lives past the à-ÿ range; str.lower must still handle it.
        assert casing.recase("CŒUR", "lower") == "CŒUR"  # all-caps -> protected
        assert casing.recase("Cœur Brisé", "lower") == "cœur brisé"

    def test_accented_sentence_start(self):
        assert casing.recase("été chaud.", "sentence") == "Été chaud."


class TestProtectHook:
    def test_protect_predicate_spares_token(self):
        # The #122/#116 seam: a caller-supplied proper-noun set is honoured.
        names = {"Marie", "Paris"}
        out = casing.recase("I met Marie in Paris", "lower", protect=names.__contains__)
        assert out == "i met Marie in Paris"


class TestActiveStyleAndApply:
    def test_active_style_validates(self, monkeypatch):
        monkeypatch.setattr(casing.settings, "get", lambda key: "lower")
        assert casing.active_style() == "lower"

    def test_active_style_unknown_falls_back(self, monkeypatch):
        monkeypatch.setattr(casing.settings, "get", lambda key: "diagonal")
        assert casing.active_style() == "preserve"

    def test_apply_casing_uses_setting(self, monkeypatch):
        monkeypatch.setattr(casing.settings, "get", lambda key: "lower")
        assert casing.apply_casing("Bonjour Monde") == "bonjour monde"

    def test_apply_casing_preserve_is_identity(self, monkeypatch):
        monkeypatch.setattr(casing.settings, "get", lambda key: "preserve")
        assert casing.apply_casing("Bonjour Monde") == "Bonjour Monde"
