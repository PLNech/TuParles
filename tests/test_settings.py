from tuparles import settings


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


class TestSettings:
    def test_default_view(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert settings.get("view") == "minimal"

    def test_put_then_get(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        settings.put("view", "full")
        assert settings.get("view") == "full"

    def test_unknown_key_is_none(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert settings.get("nope") is None

    def test_corrupt_file_falls_back(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        path = tmp_path / "tuparles" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        assert settings.get("view") == "minimal"
        settings.put("view", "full")  # heals the file
        assert settings.get("view") == "full"
