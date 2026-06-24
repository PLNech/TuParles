"""Cheat-sheet core (#83): derives from the live grammar, stays searchable.

The point of these tests is the *derive-not-hardcode* contract: if the command
vocabulary, punctuation table, or a syntax family changes, the sheet follows —
and if a punctuation regex grows a construct `humanize` can't read, we hear
about it here, not in a garbled panel.
"""

import re

from tuparles import cheatsheet, commands, punctuation, syntax


class TestEntries:
    def test_has_all_three_categories(self):
        cats = {e.category for e in cheatsheet.entries()}
        assert cats == {"Commandes", "Ponctuation", "Syntaxe"}

    def test_delete_triggers_are_derived_live(self):
        """Every command-grammar delete trigger appears in the sheet — so adding
        one to commands.py surfaces it for free, no second list to maintain."""
        sheet_text = " ".join(e.haystack() for e in cheatsheet.entries())
        for trigger in commands.vocabulary()["delete_triggers"]:
            assert trigger in sheet_text, f"{trigger!r} missing from cheat-sheet"

    def test_syntax_family_is_listed_with_its_own_help(self):
        names = {e.title for e in cheatsheet.entries() if e.category == "Syntaxe"}
        assert "quotes" in names  # registered on import of syntax_features
        quotes = next(e for e in cheatsheet.entries() if e.title == "quotes")
        assert quotes.note  # the family's summary
        assert quotes.triggers  # representative spoken forms


class TestPunctuation:
    def test_every_symbol_is_represented(self):
        symbols = {sym for _pat, sym in punctuation.SPOKEN_TO_SYMBOL}
        titles = [e.title for e in cheatsheet.entries() if e.category == "Ponctuation"]
        # comma + colon + newline etc. — at least the bare symbols are titled
        assert "," in titles and ":" in titles
        assert len(titles) == len(symbols)  # one entry per distinct symbol

    def test_comma_lists_both_languages(self):
        comma = next(
            e for e in cheatsheet.entries() if e.category == "Ponctuation" and e.title == ","
        )
        assert "virgule" in comma.triggers and "comma" in comma.triggers

    def test_humanize_known_constructs(self):
        assert cheatsheet.humanize("exclamation (?:mark|point)") == "exclamation mark/point"
        assert cheatsheet.humanize("point[- ]virgule") == "point-virgule"
        assert cheatsheet.humanize("points? de suspension") == "points de suspension"
        assert cheatsheet.humanize("point d['’]interrogation") == "point d'interrogation"

    def test_no_pattern_leaves_regex_metachars(self):
        """The drift guard: if a SPOKEN_TO_SYMBOL pattern grows a construct
        humanize doesn't handle, the readable form keeps regex syntax — fail
        here so we extend humanize (or simplify the pattern) before shipping."""
        forbidden = re.compile(r"[\[\]()?|\\]")
        for pattern, _symbol in punctuation.SPOKEN_TO_SYMBOL:
            human = cheatsheet.humanize(pattern)
            assert not forbidden.search(human), f"{pattern!r} -> {human!r} (regex leaked)"


class TestSearch:
    def test_empty_query_returns_all(self):
        assert cheatsheet.search("") == cheatsheet.entries()

    def test_accent_and_case_insensitive(self):
        # "écris" is a literal-escape prefix; search ignoring accent/case finds it
        assert cheatsheet.search("ECRIS")
        assert cheatsheet.search("ecris") == cheatsheet.search("écris")

    def test_finds_quotes_by_word(self):
        hits = cheatsheet.search("guillemets")
        assert any(e.title == "quotes" for e in hits)

    def test_miss_returns_empty(self):
        assert cheatsheet.search("zzz-no-such-command") == []

    def test_search_subsets_entries(self):
        hits = cheatsheet.search("efface")
        assert hits and all(e in cheatsheet.entries() for e in hits)


def test_catalogue_is_a_copy():
    """syntax.catalogue() must not hand out the live registry to mutate."""
    cat = syntax.catalogue()
    cat.clear()
    assert syntax.registered()  # still populated
