"""Settings-aware glue over the pure PII core (#115).

The core is tested in test_privacy.py; here we test the live-path wiring: the
`pii_redact_history` toggle, denylist-from-settings, and the analytics floor.
We stub `settings.get` so no real config file is touched.
"""

from tuparles import privacy_policy

VALID_IBAN = "FR1420041010050500013M02606"


def _stub_settings(monkeypatch, values: dict) -> None:
    monkeypatch.setattr(privacy_policy.settings, "get", lambda key: values.get(key))


class TestRedactForStorage:
    def test_off_returns_verbatim(self, monkeypatch):
        _stub_settings(monkeypatch, {"pii_redact_history": False})
        text = f"mon iban {VALID_IBAN} et clé AKIA1234567890ABCDEF"
        assert privacy_policy.redact_for_storage(text) == text

    def test_on_masks_block_tier(self, monkeypatch):
        _stub_settings(monkeypatch, {"pii_redact_history": True})
        out = privacy_policy.redact_for_storage(f"iban {VALID_IBAN} fin")
        assert VALID_IBAN not in out
        assert "<PII.IBAN>" in out

    def test_on_applies_denylist(self, monkeypatch):
        _stub_settings(
            monkeypatch,
            {"pii_redact_history": True, "pii_denylist_block": ["Ascensio"]},
        )
        out = privacy_policy.redact_for_storage("projet Ascensio confidentiel")
        assert "Ascensio" not in out and "<DENYLIST>" in out

    def test_alert_tier_never_masked(self, monkeypatch):
        _stub_settings(
            monkeypatch,
            {"pii_redact_history": True, "pii_denylist_alert": ["Helios"]},
        )
        out = privacy_policy.redact_for_storage("le client Helios")
        assert "Helios" in out  # alert-tier is surfaced elsewhere, never redacted

    def test_clean_prose_unchanged(self, monkeypatch):
        _stub_settings(monkeypatch, {"pii_redact_history": True})
        assert privacy_policy.redact_for_storage("juste une phrase") == "juste une phrase"


class TestActiveDenylist:
    def test_empty_settings_is_none(self, monkeypatch):
        _stub_settings(monkeypatch, {})
        assert privacy_policy.active_denylist() is None

    def test_built_from_terms(self, monkeypatch):
        _stub_settings(
            monkeypatch,
            {"pii_denylist_block": ["Ascensio"], "pii_denylist_alert": ["Helios"]},
        )
        dl = privacy_policy.active_denylist()
        assert dl is not None
        tiers = {f.text: f.tier for f in dl.scan("projet Ascensio pour Helios")}
        assert tiers == {"Ascensio": "block", "Helios": "alert"}


class TestAnalyticsFloor:
    def test_default_is_one(self, monkeypatch):
        _stub_settings(monkeypatch, {})
        assert privacy_policy.analytics_min_count() == 1

    def test_reads_setting(self, monkeypatch):
        _stub_settings(monkeypatch, {"pii_analytics_min_count": 3})
        assert privacy_policy.analytics_min_count() == 3

    def test_malformed_falls_back_to_one(self, monkeypatch):
        _stub_settings(monkeypatch, {"pii_analytics_min_count": "garbage"})
        assert privacy_policy.analytics_min_count() == 1

    def test_floors_at_one(self, monkeypatch):
        _stub_settings(monkeypatch, {"pii_analytics_min_count": 0})
        assert privacy_policy.analytics_min_count() == 1
