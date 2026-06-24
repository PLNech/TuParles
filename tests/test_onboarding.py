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
