from tuparles.lexicon import apply_lexicon


def test_qlors_sentence_initial():
    assert apply_lexicon("Qlors comme ça, tu parles.") == "Alors comme ça, tu parles."


def test_qlors_follows_case_mid_sentence():
    assert apply_lexicon("et qlors on continue") == "et alors on continue"


def test_boule_and_poule_request():
    assert apply_lexicon("regarde la boule request") == "regarde la pull request"
    assert apply_lexicon("la Poule request est mergée") == "la Pull request est mergée"


def test_au_fil_ligne():
    assert apply_lexicon("on fait ça au fil ligne") == "on fait ça au feeling"


def test_innocent_text_untouched():
    text = "Une poule sur un mur qui picore du pain dur."
    assert apply_lexicon(text) == text


def test_word_boundaries_respected():
    assert apply_lexicon("aqlorsb") == "aqlorsb"
