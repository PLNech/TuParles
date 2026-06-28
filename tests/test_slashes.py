"""Spoken slashes (#53). "slash" is a path separator — it becomes "/" anywhere,
gluing to its neighbours. The command ontology canonicalises known names; a "/"
after sentence punctuation keeps its space so breaks survive."""

from tuparles import settings, syntax
from tuparles.syntax_features import slashes

_CTX = syntax.SyntaxContext()


class TestCommands:
    def test_plain_command(self):
        assert slashes.apply("slash help", _CTX) == "/help"

    def test_capitalised_with_trailing_period(self):
        # Punctuation stage capitalises a line head and leaves the ASR period;
        # we still match (case-insensitive) and the period is glued, not eaten.
        assert slashes.apply("Slash help.", _CTX) == "/help."

    def test_rejoins_split_command(self):
        # The user's own example: "precompact" decoded one word or two.
        assert slashes.apply("slash pre compact", _CTX) == "/pre-compact"
        assert slashes.apply("slash precompact", _CTX) == "/pre-compact"

    def test_accented_command_folds(self):
        # The decoder writes the accent ("pré-compact"); the ontology shouldn't
        # care — fold it to the canonical "/pre-compact".
        assert slashes.apply("slash pré-compact", _CTX) == "/pre-compact"
        assert slashes.apply("slash pré compact", _CTX) == "/pre-compact"

    def test_unknown_command_accent_trimmed(self):
        # Even off-ontology, what follows a "/" is ASCII — trim the accents.
        assert slashes.apply("slash café", _CTX) == "/cafe"
        assert slashes.apply("endpoint slash dépôt", _CTX) == "endpoint/depot"

    def test_spoken_hyphen_canonicalises(self):
        # "tiret"/hyphen comes through as "-" from the punctuation stage; the
        # command join then sees "pré - compact" and lands on "/pre-compact".
        assert slashes.apply("slash pré - compact", _CTX) == "/pre-compact"
        assert slashes.apply("slash code - review", _CTX) == "/code-review"

    def test_multiword_canonical_hyphen(self):
        assert slashes.apply("slash code review", _CTX) == "/code-review"
        assert slashes.apply("slash security review", _CTX) == "/security-review"

    def test_command_keeps_its_arguments(self):
        assert slashes.apply("slash model opus", _CTX) == "/model opus"
        assert slashes.apply("slash review the diff", _CTX) == "/review the diff"

    def test_lowercases_known_command(self):
        assert slashes.apply("slash Help", _CTX) == "/help"


class TestSeparatorEverywhere:
    def test_inline_path(self):
        # The directive: fire anywhere, not just at a line head.
        assert slashes.apply("endpoint slash habits", _CTX) == "endpoint/habits"

    def test_inline_command_mention_glues(self):
        assert slashes.apply("la slash memory", _CTX) == "la/memory"

    def test_double_slash_is_comment_or_scheme(self):
        assert slashes.apply("code slash slash comment", _CTX) == "code//comment"

    def test_url_path_segments(self):
        assert slashes.apply("slash slash nech.pl slash api", _CTX) == "//nech.pl/api"

    def test_prose_separator_glues(self):
        # Accepted cost of "slash means / always": this is usually what's wanted.
        assert slashes.apply("le rapport qualité slash prix", _CTX) == (
            "le rapport qualité/prix"
        )

    def test_per_line_in_a_take(self):
        assert slashes.apply("slash compact\nmerci", _CTX) == "/compact\nmerci"

    def test_preserves_indent_at_line_head(self):
        assert slashes.apply("  slash help", _CTX) == "  /help"


class TestSentenceBreaksSurvive:
    def test_slash_after_period_keeps_its_space(self):
        # The one place we DON'T glue: across a sentence break.
        assert slashes.apply("Bonjour. Slash help", _CTX) == "Bonjour. /help"

    def test_bare_trailing_slash(self):
        assert slashes.apply("il faut un slash", _CTX) == "il faut un/"


class TestSettingsOntologyExtension:
    def test_user_can_add_a_command(self, monkeypatch):
        # "It's a setting": extend the ontology without touching the source.
        monkeypatch.setattr(
            settings,
            "get",
            lambda k: ["deploy-prod"] if k == "slash_commands" else None,
        )
        assert slashes.apply("slash deploy prod", _CTX) == "/deploy-prod"
