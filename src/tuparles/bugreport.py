"""Bug-report → prefilled GitHub issue URL (#87).

No GitHub token, no API, no server: a public repo means any shipped token is
extractable and abusable, so we just build a `.../issues/new?title=…&body=…`
URL the user opens in their browser, already filled in. The body carries an
auto-gathered environment block so a report arrives actionable without us
asking "which version / X11 or Wayland?".

Pure + offline: `issue_url()` and `environment_block()` are testable without a
browser or network. The daemon/tray opens the URL; the CLI prints it.
"""

from __future__ import annotations

import platform
from urllib.parse import quote

from tuparles.config import IS_WAYLAND

REPO = "PLNech/TuParles"
_NEW_ISSUE = f"https://github.com/{REPO}/issues/new"


def app_version() -> str:
    """Installed package version, or '?' from a bare checkout."""
    try:
        from importlib.metadata import version

        return version("tuparles")
    except Exception:
        return "?"


def environment_block() -> str:
    """The markdown an issue needs to be actionable, gathered locally."""
    session = "Wayland" if IS_WAYLAND else "X11"
    return "\n".join(
        [
            "### Environnement",
            f"- TuParles : {app_version()}",
            f"- Python : {platform.python_version()}",
            f"- OS : {platform.system()} {platform.release()}",
            f"- Session : {session}",
        ]
    )


def issue_url(title: str, body: str = "", *, include_env: bool = True) -> str:
    """A prefilled new-issue URL. The environment block is appended to the body
    so every report says where it came from; pass include_env=False to omit."""
    full_body = f"{body}\n\n{environment_block()}" if include_env else body
    return f"{_NEW_ISSUE}?title={quote(title)}&body={quote(full_body)}"
