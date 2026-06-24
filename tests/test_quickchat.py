"""Quick-chat engine (#89): anchored trigger → expansion, structurally safe.

The load-bearing test is the misfire corpus: a trigger must NOT fire when its
words appear inside ordinary prose. When in doubt, it's text.
"""

import json

import pytest

from tuparles import quickchat
from tuparles.quickchat import Phrase, expand, parse_pack

PACK = [
    Phrase("lgtm", "Looks good to me ✅"),
    Phrase("ship it", "Merging and shipping. 🚢"),
    Phrase("standup <projet>", "Standup — <projet>:\n- Hier :"),
    Phrase("merci pour la review", "Merci pour la review 🙏"),
]


class TestExpand:
    def test_exact_trigger_fires(self):
        assert expand("lgtm", PACK) == "Looks good to me ✅"

    def test_case_and_edge_punctuation_tolerant(self):
        assert expand("LGTM.", PACK) == "Looks good to me ✅"
        assert expand("  Ship it !  ", PACK) == "Merging and shipping. 🚢"

    def test_multiword_trigger(self):
        assert expand("merci pour la review", PACK) == "Merci pour la review 🙏"

    def test_no_match_returns_none(self):
        assert expand("on déploie demain matin", PACK) is None

    def test_empty_take_returns_none(self):
        assert expand("   ", PACK) is None

    def test_first_match_wins(self):
        pack = [Phrase("ok", "FIRST"), Phrase("ok", "SECOND")]
        assert expand("ok", pack) == "FIRST"


class TestMisfireCorpus:
    """A trigger's words inside a real sentence must stay text (anchored match)."""

    @pytest.mark.parametrize(
        "prose",
        [
            "lgtm mais ajoute un test d'abord",  # trigger + tail
            "je pense que lgtm sur ce coup",  # trigger mid-sentence
            "on va ship it dès que la CI passe",  # 'ship it' inside prose
            "merci pour la review détaillée que tu as faite hier",  # trigger + tail
            "un standup c'est utile",  # 'standup' word, not the macro
        ],
    )
    def test_prose_does_not_fire(self, prose):
        assert expand(prose, PACK) is None


class TestTemplates:
    def test_slot_filled_from_take(self):
        out = expand("standup billing", PACK)
        assert out == "Standup — billing:\n- Hier :"

    def test_slot_preserves_original_case(self):
        out = expand("standup Billing-API", PACK)
        assert "Billing-API" in out

    def test_empty_slot_does_not_match(self):
        # "standup" alone has nothing to fill <projet> (non-empty group) → text
        assert expand("standup", PACK) is None

    def test_unknown_slot_in_expansion_left_verbatim(self):
        pack = [Phrase("note <x>", "noté : <x> (réf <y>)")]
        assert expand("note ceci", pack) == "noté : ceci (réf <y>)"


class TestParsePack:
    def test_parses_json_string(self):
        data = json.dumps(
            {"phrases": [{"trigger": "lgtm", "expansion": "ok", "role": "eng"}]}
        )
        phrases = parse_pack(data)
        assert len(phrases) == 1
        assert phrases[0].trigger == "lgtm" and phrases[0].role == "eng"

    def test_skips_incomplete_rows(self):
        data = {
            "phrases": [
                {"trigger": "", "expansion": "x"},  # no trigger
                {"trigger": "y"},  # no expansion
                {"trigger": "ok", "expansion": "fine"},  # good
            ]
        }
        assert [p.trigger for p in parse_pack(data)] == ["ok"]

    def test_collapses_trigger_whitespace(self):
        phrases = parse_pack({"phrases": [{"trigger": "ship   it", "expansion": "x"}]})
        assert phrases[0].trigger == "ship it"


class TestLoadAndActive:
    def test_missing_file_is_empty(self, tmp_path):
        assert quickchat.load(tmp_path / "nope.json") == []

    def test_malformed_file_is_empty(self, tmp_path):
        bad = tmp_path / "phrasepack.json"
        bad.write_text("{not json")
        assert quickchat.load(bad) == []

    def test_round_trips_through_a_file(self, tmp_path):
        path = tmp_path / "phrasepack.json"
        path.write_text(
            json.dumps({"phrases": [{"trigger": "lgtm", "expansion": "ok"}]})
        )
        assert expand("lgtm", quickchat.load(path)) == "ok"

    def test_active_gated_by_setting(self, monkeypatch, tmp_path):
        path = tmp_path / "phrasepack.json"
        path.write_text(
            json.dumps({"phrases": [{"trigger": "lgtm", "expansion": "ok"}]})
        )
        monkeypatch.setattr(quickchat, "_path", lambda: path)
        monkeypatch.setattr(quickchat.settings, "get", lambda key: True)
        assert quickchat.expand_active("lgtm") == "ok"
        monkeypatch.setattr(quickchat.settings, "get", lambda key: False)
        assert quickchat.expand_active("lgtm") is None

    def test_example_pack_is_valid(self):
        from tuparles.config import REPO_ROOT

        phrases = quickchat.load(REPO_ROOT / "phrasepack.example.json")
        assert phrases  # ships parseable
        assert expand("lgtm", phrases)  # and at least one macro fires
