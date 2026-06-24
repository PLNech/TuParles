"""User settings: tiny JSON in XDG config. Hand-editable, restart-proof."""

import json
import os
from pathlib import Path

_DEFAULTS: dict[str, object] = {
    "view": "minimal",  # minimal = one-line pill | full = whole wrapped text
    "languages": [],  # ISO codes; empty = auto-detect among all 100
    "input_device": None,  # mic name; None/empty = system default
    "telemetry_enabled": True,  # LOCAL usage introspection; opt-out, never leaves the box
    # PII firewall (#102) — minimize before persist / analyze. Block-tier only
    # (checksum-validated IBAN/NIR/card + known secret prefixes): ~100% precision,
    # so auto-redaction destroys ~zero false positives. Alert-tier is never
    # auto-redacted. The denylist editor + operator profiles live in #107.
    "pii_redact_history": True,  # redact block-tier spans before they hit history.db
    "pii_denylist_block": [],  # user terms always redacted from the stored record
    "pii_denylist_alert": [],  # user terms surfaced but never auto-redacted
    "pii_analytics_min_count": 1,  # k-floor for the tag cloud; raise for k-anonymity
    # Update check (#86): opt-IN — a network call to GitHub reveals you run the
    # tool, so default off (local-first). `tuparles update` always works manually.
    "update_check_enabled": False,
    # Dict-seed bias (#68): fold codebase seed terms into Whisper's initial_prompt
    # so it spells your symbols right. Advisory only (never forces a decode), so
    # default on; the conservative post-correct is a separate gated step (#69).
    "dictseed_bias": True,
}


def _path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "tuparles" / "settings.json"


def get(key: str):
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        data = {}
    return data.get(key, _DEFAULTS.get(key))


def put(key: str, value) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data[key] = value
    path.write_text(json.dumps(data, indent=2) + "\n")
