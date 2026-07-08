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
import subprocess
from pathlib import Path
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


def _git_ref() -> str | None:
    """Short commit hash when running from a checkout, else None.

    Guarded: git absent, a pip-installed tree (site-packages isn't a repo), or a
    slow probe must never break the caller — the label just falls back to semver.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(__file__).parent), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        ref = out.stdout.strip()
        return ref if out.returncode == 0 and ref else None
    except Exception:
        return None


def version_label() -> str:
    """Human-facing version for the tray menu: `v0.3.0` or `v0.3.0 (7e161b9)`.

    Why the hash: after "Redémarrer" the user needs to *see* whether the restart
    picked up new code. The semver only moves at release time, so on a dev
    checkout it can't answer that — the commit hash can. Resolved once per
    process (the menu is built at startup), so the label IS the running code.
    """
    label = f"v{app_version()}"
    ref = _git_ref()
    return f"{label} ({ref})" if ref else label


def _capabilities_line() -> str:
    """The probed capability fingerprint (#29) — the exact cross-env detail a
    paste/focus bug needs ("which xdotool? X11 or Wayland? what's missing?"), so
    we never have to ask. Guarded: a probe failure must not break the report."""
    try:
        from tuparles import capability

        return capability.probe().report().removeprefix("capabilities: ")
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
            f"- Capacités : {_capabilities_line()}",
        ]
    )


def issue_url(title: str, body: str = "", *, include_env: bool = True) -> str:
    """A prefilled new-issue URL. The environment block is appended to the body
    so every report says where it came from; pass include_env=False to omit."""
    full_body = f"{body}\n\n{environment_block()}" if include_env else body
    return f"{_NEW_ISSUE}?title={quote(title)}&body={quote(full_body)}"
