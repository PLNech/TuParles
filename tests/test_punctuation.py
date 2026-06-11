from tuparles.punctuation import apply_spoken_punctuation as p


class TestFrench:
    def test_virgule(self):
        assert p("bonjour virgule comment ça va") == "Bonjour, comment ça va"

    def test_point_final(self):
        assert p("c'est terminé point") == "C'est terminé."

    def test_point_interrogation(self):
        assert p("tu viens point d'interrogation") == "Tu viens?"

    def test_point_exclamation(self):
        assert p("incroyable point d'exclamation") == "Incroyable!"

    def test_deux_points(self):
        assert p("trois choses deux points le code") == "Trois choses: le code"

    def test_point_virgule(self):
        assert p("d'abord point-virgule ensuite") == "D'abord; ensuite"
        assert p("d'abord point virgule ensuite") == "D'abord; ensuite"

    def test_nouvelle_ligne(self):
        assert p("titre nouvelle ligne contenu") == "Titre\nContenu"

    def test_a_la_ligne(self):
        assert p("fini à la ligne suite") == "Fini\nSuite"


class TestEnglish:
    def test_comma(self):
        assert p("first comma second") == "First, second"

    def test_period(self):
        assert p("done period") == "Done."

    def test_full_stop(self):
        assert p("done full stop") == "Done."

    def test_question_mark(self):
        assert p("ready question mark") == "Ready?"

    def test_new_line(self):
        assert p("header new line body") == "Header\nBody"

    def test_new_paragraph(self):
        assert p("intro new paragraph details") == "Intro\n\nDetails"


class TestProtectedPhrases:
    def test_point_de_vue_survives(self):
        assert p("de mon point de vue c'est bien") == "De mon point de vue c'est bien"

    def test_a_quel_point(self):
        assert p("tu sais à quel point c'est dur") == "Tu sais à quel point c'est dur"

    def test_english_point_never_maps(self):
        assert p("floating point arithmetic") == "Floating point arithmetic"
        assert p("the point of view matters") == "The point of view matters"

    def test_rond_point(self):
        assert p("prends le rond-point virgule puis à gauche") == (
            "Prends le rond-point, puis à gauche"
        )


class TestCodeSwitching:
    def test_mixed_sentence(self):
        assert p("on ship le feature virgule then we iterate point") == (
            "On ship le feature, then we iterate."
        )

    def test_tech_vocab_intact(self):
        assert p("set max_tokens to high comma sinon ça coupe") == (
            "Set max_tokens to high, sinon ça coupe"
        )


class TestTidy:
    def test_asr_already_punctuated_trigger(self):
        # ASR heard prosody AND the spoken trigger: "virgule," → ","
        assert p("bonjour virgule, ça va") == "Bonjour, ça va"

    def test_capitalize_after_sentence(self):
        assert p("fini point on continue") == "Fini. On continue"

    def test_capitalize_accented(self):
        assert p("oui point évidemment") == "Oui. Évidemment"

    def test_no_double_spaces_around_symbols(self):
        assert p("a virgule b virgule c") == "A, b, c"


class TestGluedSentences:
    def test_reopen_gap_after_period(self):
        assert p("je me pose une question.Alors je tente") == (
            "Je me pose une question. Alors je tente"
        )

    def test_filenames_survive(self):
        assert p("ouvre le fichier main.py s'il te plaît") == (
            "Ouvre le fichier main.py s'il te plaît"
        )

    def test_decimals_survive(self):
        assert p("la valeur est 3.14 environ") == "La valeur est 3.14 environ"
