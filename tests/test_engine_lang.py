from tuparles.engine import decode_language_opts


class TestDecodeLanguageOpts:
    def test_none_selected_auto_detect_once(self):
        assert decode_language_opts([]) == (None, False)

    def test_one_selected_is_forced(self):
        assert decode_language_opts(["fr"]) == ("fr", False)

    def test_two_selected_enables_code_switching(self):
        # The whole point: detect per segment, don't force one language.
        assert decode_language_opts(["en", "fr"]) == (None, True)

    def test_many_selected_still_multilingual(self):
        assert decode_language_opts(["en", "fr", "es", "it"]) == (None, True)
