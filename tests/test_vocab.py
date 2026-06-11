from tuparles import vocab


class TestSuggest:
    def test_technical_tokens_always_count(self):
        texts = ["on passe max_tokens à la config", "régler max_tokens encore"]
        assert vocab.suggest(texts) == [("max_tokens", 2)]

    def test_camel_case_and_acronyms(self):
        texts = [
            "le TaskRunner gère les KPI",
            "un TaskRunner par worker, les KPI montent",
        ]
        found = dict(vocab.suggest(texts))
        assert found == {"TaskRunner": 2, "KPI": 2}

    def test_proper_noun_mid_sentence_only(self):
        # "Demain" opens both sentences — capitalization proves nothing there.
        texts = [
            "Demain on déploie chez Palerme. Demain matin.",
            "le contrat Palerme est signé",
        ]
        assert vocab.suggest(texts) == [("Palerme", 2)]

    def test_min_count_filters_one_offs(self):
        texts = ["vu chez Palerme une fois"]
        assert vocab.suggest(texts) == []
        assert vocab.suggest(texts, min_count=1) == [("Palerme", 1)]

    def test_existing_vocab_excluded(self):
        texts = ["max_tokens partout, max_tokens toujours"]
        assert vocab.suggest(texts, existing={"MAX_TOKENS"}) == []

    def test_plain_words_ignored(self):
        texts = ["une phrase parfaitement ordinaire", "ordinaire et banale aussi"]
        assert vocab.suggest(texts) == []

    def test_ranked_by_frequency(self):
        texts = ["on cite Palerme et max_tokens"] * 2 + ["encore max_tokens ici"]
        assert vocab.suggest(texts) == [("max_tokens", 3), ("Palerme", 2)]


class TestFile:
    def test_load_skips_comments_and_blanks(self, tmp_path):
        f = tmp_path / "vocab.txt"
        f.write_text("# noms\nPalerme\n\nmax_tokens\n")
        assert vocab.load(f) == ["Palerme", "max_tokens"]

    def test_load_missing_file(self, tmp_path):
        assert vocab.load(tmp_path / "absent.txt") == []

    def test_add_dedupes_case_insensitive(self, tmp_path):
        f = tmp_path / "vocab.txt"
        f.write_text("Palerme\n")
        added = vocab.add(["palerme", "DIPI", "DIPI"], f)
        assert added == ["DIPI"]
        assert vocab.load(f) == ["Palerme", "DIPI"]

    def test_add_creates_file(self, tmp_path):
        f = tmp_path / "vocab.txt"
        assert vocab.add(["max_tokens"], f) == ["max_tokens"]
        assert vocab.load(f) == ["max_tokens"]

    def test_add_preserves_comments(self, tmp_path):
        f = tmp_path / "vocab.txt"
        f.write_text("# mes noms\nPalerme")
        vocab.add(["DIPI"], f)
        assert f.read_text() == "# mes noms\nPalerme\nDIPI\n"
