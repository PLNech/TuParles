"""What's-new on update (#82) — pure detection + section extraction, injectable."""

from tuparles import whatsnew

_CHANGELOG = """# Changelog

## Sprint 9 — 2026-06-24 · Le pare-feu se branche

### Added
- a thing

## Sprint 8 — 2026-06-24 · older

### Added
- old thing
"""


class TestLatestSection:
    def test_returns_top_block_only(self):
        sec = whatsnew.latest_section(_CHANGELOG)
        assert sec is not None
        assert sec.startswith("## Sprint 9")
        assert "a thing" in sec
        assert "Sprint 8" not in sec  # stops at the next header

    def test_none_when_no_sections(self):
        assert whatsnew.latest_section("# Changelog\n\nnothing yet") is None


class TestNewsIfNew:
    def test_shows_when_version_changed(self, monkeypatch):
        monkeypatch.setattr(whatsnew.settings, "get", lambda key: "0.0.9")
        out = whatsnew.news_if_new(current="0.1.0", changelog=_CHANGELOG)
        assert out is not None and out.startswith("## Sprint 9")

    def test_silent_when_same_version(self, monkeypatch):
        monkeypatch.setattr(whatsnew.settings, "get", lambda key: "0.1.0")
        assert whatsnew.news_if_new(current="0.1.0", changelog=_CHANGELOG) is None

    def test_silent_when_version_unknown(self, monkeypatch):
        monkeypatch.setattr(whatsnew.settings, "get", lambda key: None)
        assert whatsnew.news_if_new(current="?", changelog=_CHANGELOG) is None

    def test_first_run_shows(self, monkeypatch):
        monkeypatch.setattr(whatsnew.settings, "get", lambda key: None)
        out = whatsnew.news_if_new(current="0.1.0", changelog=_CHANGELOG)
        assert out is not None

    def test_mark_seen_persists(self, monkeypatch):
        saved = {}
        monkeypatch.setattr(whatsnew.settings, "put", lambda k, v: saved.update({k: v}))
        whatsnew.mark_seen("0.2.0")
        assert saved == {"last_seen_version": "0.2.0"}
