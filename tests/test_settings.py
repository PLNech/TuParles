from tuparles import settings


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


class TestSettings:
    def test_default_view(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert settings.get("view") == "full"

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
        assert settings.get("view") == "full"  # falls back to the default
        settings.put("view", "minimal")  # heals the file
        assert settings.get("view") == "minimal"

    def test_config_dir_override(self, tmp_path, monkeypatch):
        # The DI seam (core-extraction step 2): TUPARLES_CONFIG_DIR points the
        # config dir straight at a chosen path — no "tuparles" subdir, no XDG —
        # for Android / a server container / a test.
        monkeypatch.setenv("TUPARLES_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", "/should/be/ignored")
        assert settings._path() == tmp_path / "settings.json"
        settings.put("view", "minimal")
        assert (tmp_path / "settings.json").exists()
        assert settings.get("view") == "minimal"
