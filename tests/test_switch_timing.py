"""Synthetic language timelines; no private audio or transcript dependencies."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "score_switch_timing.py"
_SPEC = importlib.util.spec_from_file_location("score_switch_timing", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
score_switches = _MODULE.score_switches


def test_missing_switch_is_censored_not_zero_latency():
    result = score_switches([(5, "en")], [(4, "fr"), (6, "fr"), (9, None)], 10)
    assert result["confirmed"] == 0
    assert result["unconfirmed_within_horizon"] == 1
    assert result["median_confirmed_lag_s"] is None
    assert result["events"][0]["lag_s"] is None
    assert result["events"][0]["observed_horizon_s"] == 5


def test_confirmation_needs_consecutive_fresh_post_boundary_windows():
    result = score_switches(
        [(5, "en")],
        [(4, "en"), (5, "en"), (6, None), (7, "en"), (8, "en")],
        10,
        stable_windows=2,
    )
    assert result["median_confirmed_lag_s"] == 3
    assert result["events"][0]["target_already_selected_before_boundary"] is True


def test_later_boundary_cannot_rescue_preceding_miss():
    result = score_switches(
        [(5, "en"), (10, "fr")], [(6, "fr"), (10, "en"), (12, "fr")], 12
    )
    assert result["events"][0]["lag_s"] is None
    assert result["events"][1]["lag_s"] == 2
    assert result["unconfirmed_within_horizon"] == 1


def test_no_observations_does_not_invent_success():
    result = score_switches([(2, "en")], [], 8)
    assert result["events"][0]["windows"] == 0
    assert result["confirmed"] == 0


@pytest.mark.parametrize(
    "boundaries,observations,end",
    [([(5, "en")], [(6, "en"), (6, "en")], 10), ([(5, "en")], [], 4)],
)
def test_duplicate_evidence_and_invalid_horizon_rejected(boundaries, observations, end):
    with pytest.raises(ValueError):
        score_switches(boundaries, observations, end)
