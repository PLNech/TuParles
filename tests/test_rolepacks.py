"""Built-in role phrase packs (#90). The load-bearing test is the MISFIRE
corpus: prose that merely contains a built-in trigger must stay text, because a
role pack arrives from one onboarding tap rather than a trigger the user typed
themselves (so the bias has to be even more asymmetric than the personal pack —
when in doubt, it's text). Then: composition (personal wins), the preview
upgrade (#80 honest gap closed), and cheat-sheet discoverability."""

import pytest

from tuparles import quickchat, rolepacks

# Every built-in trigger, and a sentence that CONTAINS it as prose. None of the
# prose may fire — `fullmatch` anchoring is the guard, this proves it holds for
# the whole shipped catalogue (and catches a future careless un-anchored edit).
_MISFIRE_PROSE = [
    "je pense que lgtm c'est une bonne abréviation à expliquer",
    "on devrait ship it un jour mais pas aujourd'hui",
    "il faut définir la definition of done avant de commencer",
    "le rice score est un framework de priorisation connu",
    "ce détail est non bloquant pour la sortie",
    "honnêtement ça looks great mais il manque un truc",
    "notre north star c'est la rétention à trente jours",
    "rédige les okr du trimestre prochain stp",
    "fais-moi un call to action plus percutant",
    "le go to market doit être prêt pour janvier",
]


class TestMisfireCorpus:
    @pytest.mark.parametrize("prose", _MISFIRE_PROSE)
    def test_prose_containing_a_trigger_stays_text(self, prose):
        # Across every role pack at once — none should claim this prose.
        all_phrases = [
            p for role in rolepacks.roles() for p in rolepacks.pack_for(role)
        ]
        assert quickchat.expand(prose, all_phrases) is None

    def test_every_trigger_does_fire_on_an_exact_whole_take(self):
        # The flip side: said exactly (the whole take IS the trigger), it expands.
        for role in rolepacks.roles():
            for phrase in rolepacks.pack_for(role):
                assert quickchat.expand(phrase.trigger, [phrase]) == phrase.expansion

    def test_no_bare_single_common_word_triggers(self):
        # Conservatism guard: built-in triggers are distinctive (multi-word or
        # acronym), never a bare common word someone might dictate alone.
        _COMMON = {"nit", "rice", "priorité", "story", "design", "objectif"}
        for role in rolepacks.roles():
            for phrase in rolepacks.pack_for(role):
                assert phrase.trigger.lower() not in _COMMON


class TestLookups:
    def test_pack_for_none_and_unknown_are_empty(self):
        assert rolepacks.pack_for("none") == []
        assert rolepacks.pack_for(None) == []
        assert rolepacks.pack_for("astronaut") == []

    def test_known_role_has_macros(self):
        assert rolepacks.pack_for("eng")
        assert all(p.role == "eng" for p in rolepacks.pack_for("eng"))

    def test_example_is_real_and_one_line(self):
        sample = rolepacks.example("eng")
        assert sample and "→" in sample and "\n" not in sample
        assert rolepacks.example("none") is None
        assert rolepacks.example("astronaut") is None

    def test_no_literal_slot_markers_in_builtins(self):
        # Built-ins emit clean text; captured-slot <name> stays the personal
        # pack's domain (a built-in pasting "<qui>" would read as a bug).
        for role in rolepacks.roles():
            for phrase in rolepacks.pack_for(role):
                assert "<" not in phrase.expansion


@pytest.fixture
def store(monkeypatch, tmp_path):
    """In-memory settings + an empty personal pack path (no user macros)."""
    data = {"quickchat_enabled": True, "role": "none"}
    monkeypatch.setattr(quickchat.settings, "get", lambda k: data.get(k))
    monkeypatch.setattr(quickchat, "_path", lambda: tmp_path / "phrasepack.json")
    return data


class TestComposition:
    def test_role_macros_activate_via_setting(self, store):
        store["role"] = "eng"
        assert quickchat.expand_active("lgtm") == "LGTM 🚀"

    def test_role_none_activates_nothing(self, store):
        store["role"] = "none"
        assert quickchat.expand_active("lgtm") is None

    def test_personal_pack_wins_on_collision(self, store, tmp_path):
        # User redefines an eng trigger — their version must win (listed first).
        (tmp_path / "phrasepack.json").write_text(
            '{"phrases": [{"trigger": "lgtm", "expansion": "looks good to me"}]}'
        )
        store["role"] = "eng"
        assert quickchat.expand_active("lgtm") == "looks good to me"

    def test_disabled_setting_suppresses_role_macros(self, store):
        store["role"] = "eng"
        store["quickchat_enabled"] = False
        assert quickchat.expand_active("lgtm") is None


class TestDiscoverability:
    def test_role_macros_show_in_cheatsheet(self, monkeypatch, tmp_path):
        from tuparles import cheatsheet

        data = {"quickchat_enabled": True, "role": "design"}
        monkeypatch.setattr(cheatsheet.settings, "get", lambda k: data.get(k))
        monkeypatch.setattr(quickchat.settings, "get", lambda k: data.get(k))
        monkeypatch.setattr(quickchat, "_path", lambda: tmp_path / "nope.json")
        text = cheatsheet.as_text("design review")
        assert "design review" in text


class TestOnboardingPreviewUpgrade:
    def test_role_preview_shows_a_real_macro(self):
        from tuparles import onboarding

        preview = onboarding.preview("role", "eng")
        assert "lgtm" in preview.lower() and "→" in preview

    def test_role_none_preview_is_dash(self):
        from tuparles import onboarding

        assert onboarding.preview("role", "none") == "—"
