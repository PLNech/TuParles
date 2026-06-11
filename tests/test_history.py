from tuparles import history


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


class TestHistory:
    def test_record_and_recent(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        history.record("première dictée", engine="GpuEngine")
        history.record("second one, code-switché")
        rows = history.recent(5)
        assert [text for _ts, text in rows] == [
            "second one, code-switché",
            "première dictée",
        ]

    def test_last(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert history.last() is None
        history.record("hello")
        assert history.last() == "hello"

    def test_search(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        history.record("parlons de max_tokens")
        history.record("rien à voir")
        rows = history.search("max_tokens")
        assert len(rows) == 1
        assert rows[0][1] == "parlons de max_tokens"

    def test_empty_text_not_recorded(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        history.record("")
        assert history.last() is None

    def test_persists_across_connections(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        history.record("durable")
        # every call opens a fresh connection — this is the cross-restart story
        assert history.last() == "durable"
        assert (tmp_path / "tuparles" / "history.db").exists()
