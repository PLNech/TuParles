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


class TestTelemetry:
    def test_metadata_stored_and_wpm_derived(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        history.record(
            "dix mots exactement pour faire un test de débit propre",
            audio_s=30.0, decode_s=1.5, deliver_s=0.1,
            lang="fr", lang_prob=0.97,
        )
        s = history.summarize()
        assert s["takes"] == 1
        assert s["words"] == 10
        assert s["avg_wpm"] == 20.0  # 10 words / half a minute
        assert s["decode_x_realtime"] == 20.0
        assert s["langs"] == [("fr", 1)]

    def test_metadata_optional(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        history.record("sans métadonnées")
        s = history.summarize()
        assert s["takes"] == 1
        assert s["avg_wpm"] is None

    def test_migration_from_old_schema(self, tmp_path, monkeypatch):
        import sqlite3

        _isolate(tmp_path, monkeypatch)
        path = tmp_path / "tuparles" / "history.db"
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE dictations (id INTEGER PRIMARY KEY,"
                " ts TEXT NOT NULL, text TEXT NOT NULL,"
                " engine TEXT NOT NULL DEFAULT '')"
            )
            conn.execute(
                "INSERT INTO dictations (ts, text) VALUES ('2026-06-11', 'vieux')"
            )
        history.record("nouveau", audio_s=6.0, lang="en")  # triggers migration
        assert [t for _, t in history.recent(5)] == ["nouveau", "vieux"]
        assert history.summarize()["langs"] == [("en", 1)]
