"""Score language-switch timing without carrying audio or transcript content.

Times are audio-window end times, not decoder wall-clock times. A missing switch
is censored at the next boundary or end of observation; it is never a zero lag.
Language labels must be supplied by the evaluation fixture, independently of the
preview being scored. Automatically screened fixtures still need that caveat.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from itertools import pairwise


def score_switches(
    boundaries: Sequence[tuple[float, str]],
    observations: Sequence[tuple[float, str | None]],
    end_s: float,
    *,
    stable_windows: int = 1,
) -> dict:
    """Return numeric metrics and per-boundary language/timing metadata only.

    Confirmation requires ``stable_windows`` consecutive post-boundary windows.
    A different/unknown language resets that streak. The latency is to the
    confirming window; decoder runtime should be reported separately.
    """
    if not math.isfinite(end_s) or end_s < 0:
        raise ValueError("end_s must be finite and non-negative")
    if not isinstance(stable_windows, int) or stable_windows < 1:
        raise ValueError("stable_windows must be a positive integer")
    for rows in (boundaries, observations):
        times = [time for time, _ in rows]
        if any(not math.isfinite(time) or not 0 <= time <= end_s for time in times):
            raise ValueError("timestamps must lie within the observation interval")
        if any(a >= b for a, b in pairwise(times)):
            raise ValueError("timestamps must be strictly increasing")
    if any(not language for _, language in boundaries):
        raise ValueError("boundaries require a target language")

    events = []
    for index, (boundary, target) in enumerate(boundaries):
        final = index + 1 == len(boundaries)
        horizon = end_s if final else boundaries[index + 1][0]
        windows = [
            (time, language)
            for time, language in observations
            if boundary <= time and (time <= horizon if final else time < horizon)
        ]
        previous = [language for time, language in observations if time < boundary]
        streak = 0
        confirmed = None
        for time, language in windows:
            streak = streak + 1 if language == target else 0
            if streak >= stable_windows:
                confirmed = time
                break
        events.append(
            {
                "boundary_s": boundary,
                "target_language": target,
                "observed_horizon_s": horizon - boundary,
                "windows": len(windows),
                "unknown_windows": sum(language is None for _, language in windows),
                "target_already_selected_before_boundary": bool(
                    previous and previous[-1] == target
                ),
                "confirmed": confirmed is not None,
                "lag_s": None if confirmed is None else confirmed - boundary,
            }
        )
    lags = [event["lag_s"] for event in events if event["lag_s"] is not None]
    return {
        "switches": len(events),
        "confirmed": len(lags),
        "unconfirmed_within_horizon": len(events) - len(lags),
        "median_confirmed_lag_s": statistics.median(lags) if lags else None,
        "stable_windows": stable_windows,
        "events": events,
    }
