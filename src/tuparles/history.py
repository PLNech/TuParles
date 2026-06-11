"""Dictation history: every landed transcript, locally, forever searchable.

SQLite in XDG data home — survives repo moves and reinstalls, never synced
to git (it's personal speech, it stays on the machine).
"""

import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dictations (
    id     INTEGER PRIMARY KEY,
    ts     TEXT NOT NULL,
    text   TEXT NOT NULL,
    engine TEXT NOT NULL DEFAULT ''
)
"""


def _db_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "tuparles" / "history.db"


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    return conn


def record(text: str, engine: str = "") -> None:
    if not text:
        return
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    with closing(_conn()) as conn, conn:
        conn.execute(
            "INSERT INTO dictations (ts, text, engine) VALUES (?, ?, ?)",
            (ts, text, engine),
        )


def recent(n: int = 8) -> list[tuple[str, str]]:
    """Newest first: [(ts, text), …]."""
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT ts, text FROM dictations ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return rows


def search(query: str, n: int = 20) -> list[tuple[str, str]]:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT ts, text FROM dictations WHERE text LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (f"%{query}%", n),
        ).fetchall()
    return rows


def last() -> str | None:
    rows = recent(1)
    return rows[0][1] if rows else None
