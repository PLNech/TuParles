"""What's-new on update (#82) — show the latest CHANGELOG section once after the
installed version changes.

The reusable core: detect "version changed since you last saw the news" and
extract the top CHANGELOG section. Pure + injectable, so it's testable and the
surface (a `tuparles whatsnew` CLI; later a tray card) just renders the string.
A missing CHANGELOG (non-dev install) degrades to None, never raises.
"""

from __future__ import annotations

from tuparles import settings
from tuparles.bugreport import app_version
from tuparles.config import REPO_ROOT

_CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def latest_section(text: str) -> str | None:
    """The top `## …` block of a CHANGELOG (header + body, trimmed), or None.

    The leading `# Changelog` title is skipped; we return from the first sprint
    header up to the next one."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip() or None


def _changelog_text() -> str | None:
    try:
        return _CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return None


def news_if_new(
    *, current: str | None = None, changelog: str | None = None
) -> str | None:
    """The latest section IF the installed version differs from the last one the
    user was shown (and is known). None otherwise. Does NOT mark seen — the
    caller does that once it has actually displayed the news."""
    current = app_version() if current is None else current
    if current in ("", "?"):
        return None
    if settings.get("last_seen_version") == current:
        return None
    text = _changelog_text() if changelog is None else changelog
    return latest_section(text) if text else None


def mark_seen(version: str | None = None) -> None:
    """Record that the user has seen the news for `version` (default current)."""
    settings.put("last_seen_version", version or app_version())
