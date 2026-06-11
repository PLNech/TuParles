from tuparles.languages import LANGUAGES, snap_language


class TestCatalog:
    def test_core_languages_present(self):
        assert LANGUAGES["fr"] == "French"
        assert LANGUAGES["en"] == "English"
        assert len(LANGUAGES) == 100


class TestSnap:
    PROBS = [("ru", 0.41), ("fr", 0.32), ("en", 0.20), ("it", 0.07)]

    def test_snaps_to_best_selected(self):
        # The Вт scenario: detector says Russian, user only speaks fr/en.
        assert snap_language(self.PROBS, ["fr", "en"]) == "fr"

    def test_respects_ranking_within_selection(self):
        assert snap_language(self.PROBS, ["en", "it"]) == "en"

    def test_nothing_matches_falls_back(self):
        assert snap_language(self.PROBS, ["ja", "ko"]) is None

    def test_empty_probs(self):
        assert snap_language([], ["fr"]) is None
