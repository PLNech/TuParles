"""Update checker via the public GitHub Releases API (#86).

Opt-in and tokenless: a network call reveals you run the tool, so it's OFF by
default (local-first ethos) and gated by `update_check_enabled`. No auth — the
unauthenticated Releases endpoint is plenty for an occasional check, and a
public repo can't ship a usable token anyway (same reasoning as #87).

The version comparison is pure and tested; the fetch is injectable so tests
never touch the network, and every failure path returns `None` rather than
raising — an update check must never break a launch.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from tuparles import settings
from tuparles.bugreport import REPO, app_version

_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


def _version_tuple(tag: str) -> tuple[int, ...]:
    """'v1.2.0' / '1.2' → (1, 2, 0...). Non-numeric parts drop to 0 so a weird
    tag sorts low rather than crashing the comparison."""
    cleaned = tag.strip().lstrip("vV").split("+")[0].split("-")[0]
    parts = []
    for piece in cleaned.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """True when `latest` is a strictly higher version than `current`.
    Unknown current ('?') is treated as oldest, so a release always shows."""
    if current in ("", "?"):
        return True
    return _version_tuple(latest) > _version_tuple(current)


def _default_fetch(url: str, timeout: float) -> str:
    from urllib.request import Request, urlopen

    req = Request(url, headers={"Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    available: bool
    url: str


def check(
    *, timeout: float = 4.0, fetch: Callable[[str, float], str] | None = None
) -> UpdateInfo | None:
    """Query the latest release; None on any failure (offline, rate-limit, bad
    JSON). Never raises — a dead update check must not cost you a launch."""
    fetcher = fetch or _default_fetch
    try:
        data = json.loads(fetcher(_LATEST, timeout))
        tag = data["tag_name"]
        url = data.get("html_url", f"https://github.com/{REPO}/releases")
    except Exception:
        return None
    current = app_version()
    return UpdateInfo(current, tag, is_newer(tag, current), url)


def check_if_enabled(**kw) -> UpdateInfo | None:
    """The gated entry point: respects the `update_check_enabled` opt-out
    (default off). Manual `tuparles update` calls `check()` directly instead."""
    if not settings.get("update_check_enabled"):
        return None
    return check(**kw)
