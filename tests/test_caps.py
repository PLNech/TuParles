"""Voice-caps region family (#59). The load-bearing test is the misfire corpus:
prose that LOOKS like a caps command must never fire. Safety is the require-close
interlock — a region is only ever a complete open…close pair."""

import pytest

from tuparles import syntax
from tuparles.syntax_features import caps

_CTX = syntax.SyntaxContext()

# Prose that mentions the trigger words but is NOT a command. None may fire.
_MISFIRE_PROSE = [
    "je l'ai écrit en majuscule",
    "le titre est tout en majuscules dans le document",
    "all caps is hard to read",
    "appuie sur la touche caps lock",
    "on parle de majuscules et de minuscules",
    "the end caps of the shelf were loose",
    "je préfère écrire en minuscules",
]


class TestRegionFires:
    def test_french_region(self):
        out = caps.apply("tout en majuscules attention fin des majuscules", _CTX)
        assert out == "ATTENTION"

    def test_english_region(self):
        assert caps.apply("all caps hello world end caps", _CTX) == "HELLO WORLD"

    def test_region_inside_a_sentence(self):
        out = caps.apply("dis all caps danger end caps maintenant", _CTX)
        assert out == "dis DANGER maintenant"

    def test_two_regions(self):
        out = caps.apply("all caps a end caps et all caps b end caps", _CTX)
        assert out == "A et B"

    def test_unicode_uppercases(self):
        out = caps.apply("tout en majuscules été fin des majuscules", _CTX)
        assert out == "ÉTÉ"

    def test_close_variants(self):
        assert caps.apply("en majuscules ok fin majuscules", _CTX) == "OK"
        assert caps.apply("all caps go caps off", _CTX) == "GO"

    def test_minuscule_closes_one_way(self):
        # Switching to the other mode ends the shout (one-way synonym).
        assert caps.apply("tout en majuscules secret minuscule", _CTX) == "SECRET"
        assert caps.apply("en majuscules x en minuscules", _CTX) == "X"
        assert caps.apply("all caps go lowercase", _CTX) == "GO"


class TestRequireCloseInterlock:
    def test_lone_open_stays_text(self):
        # The whole point: an unclosed open must NOT shout the rest of the take.
        src = "tout en majuscules et la suite reste normale"
        assert caps.apply(src, _CTX) == src

    def test_close_without_open_is_inert(self):
        src = "voici la fin des majuscules dont je parlais"
        assert caps.apply(src, _CTX) == src


class TestMisfireCorpus:
    @pytest.mark.parametrize("text", _MISFIRE_PROSE)
    def test_prose_does_not_fire(self, text):
        assert caps.apply(text, _CTX) == text


class TestIntegration:
    def test_registered_in_catalogue(self):
        assert "caps" in syntax.registered()

    def test_runs_through_apply_syntax(self):
        out = syntax.apply_syntax("all caps hi end caps")
        assert out == "HI"


class TestCompositionWithCasing:
    def test_region_caps_survive_lower_style(self, monkeypatch):
        # A happy accident worth pinning: an all-caps region reads as an ACRONYM
        # to #120's `lower` guard, so explicit caps survive descriptive lowercase
        # for free. (The #59×#120 conflict only bites future next-word single
        # capitals, e.g. "Paris"->"paris"; deferred to #121.)
        from tuparles import casing
        from tuparles.pipeline import postprocess

        monkeypatch.setattr(
            casing.settings,
            "get",
            lambda key: "lower" if key == "casing_style" else None,
        )
        assert "HELLO" in postprocess("all caps hello end caps")
