"""Deterministic PII core (#103): high-assurance, no model, no torch.

These layers carry block authority, so they must be precise: a checksum either
validates or it doesn't; a denylist matches whole tokens or not at all.
"""

from collections import Counter

from tuparles import privacy
from tuparles.privacy import Denylist

# valid by checksum (computed via python-stdnum)
VALID_IBAN = "FR1420041010050500013M02606"
VALID_NIR = "255081416802538"
VALID_CARD = "4111111111111111"  # Luhn-valid test number


class TestSecrets:
    def test_known_prefixes_block(self):
        text = "key AKIA1234567890ABCDEF and token ghp_" + "a" * 36
        kinds = {f.kind for f in privacy.find_secrets(text)}
        assert "secret.aws_key" in kinds
        assert "secret.github_pat" in kinds
        assert all(
            f.tier == "block"
            for f in privacy.find_secrets(text)
            if f.kind.startswith("secret") and f.kind != "secret.high_entropy"
        )

    def test_pem_and_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36"
        assert any(f.kind == "secret.jwt" for f in privacy.find_secrets(jwt))
        pem = "-----BEGIN RSA PRIVATE KEY-----"
        assert any(f.kind == "secret.pem" for f in privacy.find_secrets(pem))

    def test_high_entropy_is_alert_not_block(self):
        text = "deploy with aG38fjQ9zPbX72KdLm05wRtY1cVn4eH6"
        hits = [
            f for f in privacy.find_secrets(text) if f.kind == "secret.high_entropy"
        ]
        assert hits and hits[0].tier == "alert"

    def test_plain_prose_is_clean(self):
        assert privacy.find_secrets("on parle de RequestOptions et de faceting") == []


class TestStructured:
    def test_email_iban_nir_card_block(self):
        text = f"mail a@b.com iban {VALID_IBAN} nir {VALID_NIR} carte {VALID_CARD}"
        kinds = {f.kind for f in privacy.find_structured(text)}
        assert kinds == {"pii.email", "pii.iban", "pii.fr_nir", "pii.card"}

    def test_invalid_checksum_not_flagged(self):
        # a 15-digit number with a wrong NIR control key must NOT be flagged
        text = "numero 295057524500158 pas valide"
        assert all(f.kind != "pii.fr_nir" for f in privacy.find_structured(text))


class TestDenylist:
    def test_block_and_alert_tiers(self):
        dl = Denylist.from_terms(block=["Ascensio"], alert=["Helios"])
        findings = {f.text: f.tier for f in dl.scan("projet Ascensio pour Helios")}
        assert findings == {"Ascensio": "block", "Helios": "alert"}

    def test_accent_and_leet_normalized(self):
        dl = Denylist.from_terms(block=["Ascensio"])
        # accented + leetspeak variants both normalize to the same entry
        assert len(dl.scan("ascénsio et 4sc3nsio")) == 2

    def test_scunthorpe_safe(self):
        # a banned token must not match as a substring of a legit word
        dl = Denylist.from_terms(block=["cunt"])
        assert dl.scan("the town of Scunthorpe") == []


class TestFloor:
    def test_drops_rare_terms(self):
        counts = Counter({"facette": 9, "guillaume": 1, "requestoptions": 4})
        floored = privacy.frequency_floor(counts, k=2)
        assert "guillaume" not in floored
        assert floored["facette"] == 9


class TestRedact:
    def test_masks_block_leaves_alert(self):
        dl = Denylist.from_terms(block=["Ascensio"], alert=["Helios"])
        out = privacy.redact("client Ascensio projet Helios mail a@b.com", denylist=dl)
        assert "Ascensio" not in out and "<DENYLIST>" in out
        assert "<PII.EMAIL>" in out
        assert "Helios" in out  # alert tier is surfaced, never auto-redacted

    def test_clean_text_unchanged(self):
        assert privacy.redact("juste une phrase normale") == "juste une phrase normale"

    def test_scan_combines_and_sorts(self):
        dl = Denylist.from_terms(block=["Ascensio"])
        findings = privacy.scan(f"a@b.com puis Ascensio puis {VALID_IBAN}", denylist=dl)
        assert [f.start for f in findings] == sorted(f.start for f in findings)
        assert {f.kind for f in findings} >= {"pii.email", "denylist", "pii.iban"}
