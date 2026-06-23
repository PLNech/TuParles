from tuparles.languages import LANGUAGES


class TestCatalog:
    def test_core_languages_present(self):
        assert LANGUAGES["fr"] == "French"
        assert LANGUAGES["en"] == "English"
        assert len(LANGUAGES) == 100
