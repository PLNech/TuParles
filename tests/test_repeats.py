from tuparles.repeats import collapse_repeats as c


class TestLoops:
    def test_dipi_loop_from_the_wild(self):
        assert c("Un autre acteur assume. DIPI. DIPI. DIPI. DIPI.") == (
            "Un autre acteur assume. DIPI."
        )

    def test_long_loop(self):
        assert c("Merci. " * 7 + "Au revoir.") == "Merci. Au revoir."

    def test_question_loop(self):
        assert c("Tu viens ? Tu viens ? Tu viens ? Bon.") == "Tu viens ? Bon."

    def test_case_insensitive_run(self):
        assert c("Stop. stop. STOP. Fini.") == "Stop. Fini."


class TestLegitSpeechSurvives:
    def test_double_for_emphasis(self):
        assert c("Non. Non. On refait.") == "Non. Non. On refait."

    def test_single_sentence(self):
        assert c("Rien à signaler.") == "Rien à signaler."

    def test_distinct_sentences(self):
        text = "On ship le feature. Then we iterate. C'est parti."
        assert c(text) == text

    def test_separated_repeats_survive(self):
        # Same sentence twice but with another between: not a loop.
        text = "Oui. Peut-être. Oui. Peut-être. Bon."
        assert c(text) == text

    def test_empty(self):
        assert c("") == ""


class TestSpacingPreserved:
    def test_newlines_survive(self):
        assert c("Titre.\nLigne un. Ligne deux.") == "Titre.\nLigne un. Ligne deux."

    def test_newline_after_collapsed_run(self):
        assert c("Go. Go. Go. Go.\nSuite.") == "Go.\nSuite."
