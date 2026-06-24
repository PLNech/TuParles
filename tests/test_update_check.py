"""Update checker (#86) — pure compare + injected fetch, never touches the network.

The version comparison is the logic worth pinning; the fetch is passed in so a
test can simulate GitHub, an offline box, or a rate-limit without a socket.
"""

import json

from tuparles import update_check


class TestIsNewer:
    def test_strictly_higher_wins(self):
        assert update_check.is_newer("v1.2.0", "1.1.9")
        assert update_check.is_newer("2.0.0", "1.9.9")

    def test_equal_or_older_is_not_newer(self):
        assert not update_check.is_newer("1.2.0", "1.2.0")
        assert not update_check.is_newer("1.0.0", "1.2.0")

    def test_v_prefix_and_short_tags(self):
        assert update_check.is_newer("v1.2", "1.1")
        assert not update_check.is_newer("v1.2", "1.2.0")

    def test_unknown_current_always_offers(self):
        assert update_check.is_newer("0.0.1", "?")
        assert update_check.is_newer("0.0.1", "")

    def test_weird_tag_sorts_low_not_crash(self):
        assert not update_check.is_newer("nightly", "1.0.0")  # 'nightly' → (0,)


class TestCheck:
    def _fetch(self, payload):
        return lambda url, timeout: json.dumps(payload)

    def test_reports_available_update(self, monkeypatch):
        monkeypatch.setattr(update_check, "app_version", lambda: "1.0.0")
        info = update_check.check(
            fetch=self._fetch({"tag_name": "v1.3.0", "html_url": "u"})
        )
        assert info is not None
        assert info.available and info.latest == "v1.3.0" and info.url == "u"

    def test_up_to_date(self, monkeypatch):
        monkeypatch.setattr(update_check, "app_version", lambda: "1.3.0")
        info = update_check.check(fetch=self._fetch({"tag_name": "v1.3.0"}))
        assert info is not None and not info.available

    def test_network_failure_returns_none(self):
        def boom(url, timeout):
            raise OSError("offline")

        assert update_check.check(fetch=boom) is None

    def test_bad_json_returns_none(self):
        assert update_check.check(fetch=lambda u, t: "not json") is None


class TestGate:
    def test_disabled_by_default_skips(self, monkeypatch):
        monkeypatch.setattr(update_check.settings, "get", lambda key: None)
        # fetch would raise if called — proves the gate short-circuits first
        called = []
        update_check.check_if_enabled(fetch=lambda u, t: called.append(1) or "{}")
        assert called == []

    def test_enabled_runs_check(self, monkeypatch):
        monkeypatch.setattr(update_check.settings, "get", lambda key: True)
        monkeypatch.setattr(update_check, "app_version", lambda: "1.0.0")
        info = update_check.check_if_enabled(
            fetch=lambda u, t: json.dumps({"tag_name": "v2.0.0"})
        )
        assert info is not None and info.available
