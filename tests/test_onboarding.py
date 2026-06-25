"""« Comment Tu Parles ? » onboarding core (#80). Pure, no-GPU. Covers the three
triggers (first-launch / post-update / manual replay), the live preview running
the real casing engine, and choice application to settings."""

import pytest

from tuparles import onboarding
from tuparles.settings import _DEFAULTS


@pytest.fixture
def store(monkeypatch):
    """In-memory settings backing, pre-seeded with the real defaults."""
    data: dict = {}
    monkeypatch.setattr(
        onboarding.settings, "get", lambda k: data.get(k, _DEFAULTS.get(k))
    )
    monkeypatch.setattr(onboarding.settings, "put", lambda k, v: data.__setitem__(k, v))
    return data


class TestTriggers:
    def test_first_launch_offers_all(self, store):
        assert onboarding.axes() == list(onboarding.AXES)
        assert onboarding.should_show()

    def test_finished_offers_nothing(self, store):
        store["onboarding_done"] = True
        store["onboarding_axes_seen"] = [a.key for a in onboarding.AXES]
        assert onboarding.axes() == []
        assert not onboarding.should_show()

    def test_post_update_offers_only_new_axis(self, store):
        # Done, but a release added "view" the user has never been offered.
        store["onboarding_done"] = True
        store["onboarding_axes_seen"] = [
            a.key for a in onboarding.AXES if a.key != "view"
        ]
        offered = onboarding.axes()
        assert [a.key for a in offered] == ["view"]

    def test_force_replay_offers_all_even_when_done(self, store):
        store["onboarding_done"] = True
        store["onboarding_axes_seen"] = [a.key for a in onboarding.AXES]
        assert onboarding.axes(force=True) == list(onboarding.AXES)


class TestDefaults:
    def test_defaults_are_conservative(self, store):
        assert onboarding.defaults() == {
            "casing_style": "preserve",
            "role": "none",
            "languages": "fr+en",
            "view": "minimal",
        }


class TestPreview:
    def test_casing_morphs_through_real_engine(self):
        assert onboarding.preview("casing_style", "lower") == "comment tu parles ?"
        assert onboarding.preview("casing_style", "preserve") == onboarding.SAMPLE

    def test_view_preview(self):
        assert onboarding.preview("view", "minimal").startswith("▸")
        assert onboarding.preview("view", "full") == onboarding.SAMPLE

    def test_unknown_key_returns_sample(self):
        assert onboarding.preview("nope", "x") == onboarding.SAMPLE


class TestApply:
    def test_writes_choices_and_marks_done(self, store):
        onboarding.apply_choices({"casing_style": "lower", "view": "full"})
        assert store["casing_style"] == "lower"
        assert store["view"] == "full"
        assert store["onboarding_done"] is True
        assert store["onboarding_axes_seen"] == [a.key for a in onboarding.AXES]

    def test_languages_parsed_to_list(self, store):
        onboarding.apply_choices({"languages": "fr"})
        assert store["languages"] == ["fr"]
        onboarding.apply_choices({"languages": "auto"})
        assert store["languages"] == []

    def test_ignores_value_outside_choices(self, store):
        onboarding.apply_choices({"casing_style": "diagonal"})
        assert "casing_style" not in store  # bogus value never written
        assert store["onboarding_done"] is True  # but onboarding still completes

    def test_keep_defaults_commits_conservative_set(self, store):
        onboarding.apply_choices(onboarding.defaults())
        assert store["casing_style"] == "preserve"
        assert store["languages"] == ["fr", "en"]
        assert store["onboarding_done"] is True


class TestCliView:
    """The no-Qt walkthrough (`tuparles onboarding`) — the graceful fallback view
    over the same core. Drives it by feeding scripted answers to input()."""

    def _run(self, monkeypatch, answers, *, replay=False):
        from types import SimpleNamespace

        from tuparles import cli

        it = iter(answers)
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))
        cli._onboarding(SimpleNamespace(replay=replay))

    def test_number_picks_choice_blank_leaves_untouched(self, store, monkeypatch):
        # casing → "2" (lower); role blank; languages → "2" (fr); view blank.
        self._run(monkeypatch, ["2", "", "2", ""])
        assert store["casing_style"] == "lower"
        assert store["languages"] == ["fr"]
        assert "role" not in store  # blank wrote nothing
        assert "view" not in store
        assert store["onboarding_done"] is True

    def test_quit_keeps_rest_and_still_marks_done(self, store, monkeypatch):
        # Pick casing, then quit — later axes never written, but onboarding done.
        self._run(monkeypatch, ["2", "q"])
        assert store["casing_style"] == "lower"
        assert "languages" not in store
        assert store["onboarding_done"] is True

    def test_bad_input_is_ignored_not_applied(self, store, monkeypatch):
        # Out-of-range / non-numeric leaves the axis untouched.
        self._run(monkeypatch, ["9", "nope", "x", "5"])
        assert "casing_style" not in store
        assert store["onboarding_done"] is True

    def test_already_done_short_circuits(self, store, monkeypatch, capsys):
        store["onboarding_done"] = True
        store["onboarding_axes_seen"] = [a.key for a in onboarding.AXES]
        # No input should be consumed; an empty iterator proves it.
        self._run(monkeypatch, [])
        assert "Déjà configuré" in capsys.readouterr().out

    def test_replay_offers_all_even_when_done(self, store, monkeypatch):
        store["onboarding_done"] = True
        store["onboarding_axes_seen"] = [a.key for a in onboarding.AXES]
        self._run(monkeypatch, ["3", "", "", ""], replay=True)
        assert store["casing_style"] == "sentence"
