"""The command parser, with the misfire matrix front and centre.

The contract that matters most: PROSE NEVER PARSES AS A COMMAND. A false
positive edits the user's text against their will; a false negative just types
a command they retry. So the prose corpus is large and deliberately adversarial
— sentences that mention "efface", start with "dis"/"say", or contain a lone
trigger — and every one of them must classify as None.
"""

from tuparles.commands import MAX_COMMAND_TOKENS, Command, parse

# --- Prose that must NEVER be read as a command ------------------------------
PROSE = [
    "",
    "   ",
    "Bonjour, comment vas-tu aujourd'hui ?",
    "Je vais effacer le tableau après la réunion.",  # single trigger, in prose
    "Il faut supprimer ce fichier avant de commit.",
    "Delete the row only if the test fails.",
    "Can you remove the trailing whitespace here?",
    "On efface tout et on recommence, comme dit la chanson.",
    "Dis donc, c'est une belle journée !",  # starts with "dis", not an escape
    "Dis-moi ce que tu en penses.",
    "Say hello to the team for me.",
    "Type the password and press enter.",
    "Write a function that returns the sum.",
    "I think we should ship this, not chip away at it.",
    "Trois mots suffisent parfois.",  # number + unit but no trigger
    "La dernière ligne du fichier est vide.",
    "Annuler la réservation coûte vingt euros.",  # 'annuler' inside a sentence
    "un peu plus de café, s'il te plaît",  # nudge phrase buried in prose
    "ouvre la porte quand tu rentres",  # 'ouvre' but not a terminal
    "efface",  # single trigger, no doubling
    "supprimer",
    "delete",
    "undo the last migration on staging please right now okay",  # long
]


def test_prose_never_parses_as_command():
    for text in PROSE:
        assert parse(text) is None, f"misfired on prose: {text!r}"


# --- Delete: the doubled-trigger interlock -----------------------------------
def test_single_trigger_is_not_a_command():
    assert parse("efface") is None
    assert parse("efface le mot") is None  # still single → prose


def test_doubled_trigger_deletes_one_word_by_default():
    cmd = parse("efface efface")
    assert cmd == Command("delete", unit="word", count=1)


def test_doubled_trigger_english():
    assert parse("delete delete") == Command("delete", unit="word", count=1)


def test_mixed_triggers_count_as_doubling():
    # code-switch / infinitive mix still activates
    assert parse("efface effacer") == Command("delete", unit="word", count=1)
    assert parse("supprime efface") == Command("delete", unit="word", count=1)


def test_extra_repeats_add_count():
    assert parse("efface efface efface") == Command("delete", "word", 2)
    assert parse("efface efface efface efface") == Command("delete", "word", 3)


def test_explicit_count_wins_over_repeats():
    assert parse("efface efface efface trois mots") == Command("delete", "word", 3)
    assert parse("efface efface 5 mots") == Command("delete", "word", 5)


def test_number_words_fr_and_en():
    assert parse("efface efface deux mots") == Command("delete", "word", 2)
    assert parse("efface efface trois mots") == Command("delete", "word", 3)
    assert parse("delete delete three words") == Command("delete", "word", 3)


def test_units():
    assert parse("efface efface un caractère") == Command("delete", "char", 1)
    assert parse("efface efface trois caractères") == Command("delete", "char", 3)
    assert parse("efface efface la ligne") == Command("delete", "line", 1)
    assert parse("delete delete two lines") == Command("delete", "line", 2)


def test_all_ignores_count():
    assert parse("efface efface tout") == Command("delete", "all", 1)
    assert parse("delete delete everything") == Command("delete", "all", 1)


def test_les_trois_derniers_mots():
    assert parse("efface efface les trois derniers mots") == Command(
        "delete", "word", 3
    )


# --- Undo / nudge / terminal -------------------------------------------------
def test_undo():
    for word in ("annule", "annuler", "undo"):
        assert parse(word) == Command("undo")


def test_nudge_more_and_less():
    assert parse("un peu plus") == Command("nudge", direction="more")
    assert parse("a bit more") == Command("nudge", direction="more")
    assert parse("un peu moins") == Command("nudge", direction="less")
    assert parse("a bit less") == Command("nudge", direction="less")


def test_bare_more_less_are_prose():
    # too collision-prone to be commands on their own
    assert parse("plus") is None
    assert parse("more") is None
    assert parse("moins") is None
    assert parse("encore") is None


def test_open_terminal():
    assert parse("ouvre un terminal") == Command("open_terminal")
    assert parse("open a terminal") == Command("open_terminal")
    assert parse("nouveau terminal") == Command("open_terminal")


# --- Literal escape ----------------------------------------------------------
def test_literal_escape_unwraps_a_command():
    cmd = parse('dis "efface efface"')
    assert cmd == Command("literal", text="efface efface")


def test_literal_escape_preserves_inner_case():
    cmd = parse('say "Delete Delete"')
    assert cmd.action == "literal"
    assert cmd.text == "Delete Delete"


def test_literal_only_fires_when_remainder_is_a_command():
    # 'dis bonjour' is just prose starting with "dis" — not an escape
    assert parse("dis bonjour") is None
    assert parse("say hello") is None


def test_literal_escape_without_quotes():
    assert parse("dis efface efface") == Command("literal", text="efface efface")


# --- Normalization robustness ------------------------------------------------
def test_trailing_punctuation_and_case():
    assert parse("Efface efface.") == Command("delete", "word", 1)
    assert parse("EFFACE EFFACE !") == Command("delete", "word", 1)
    assert parse("  efface   efface  ") == Command("delete", "word", 1)


def test_too_long_is_prose():
    long_take = "efface efface " + " ".join(["mot"] * MAX_COMMAND_TOKENS)
    assert parse(long_take) is None
