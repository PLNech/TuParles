"""Local event sink: a sibling `events` table in the tuparles data store.

Events are low-frequency (per-command, per-dictation), so writes stay
synchronous — same store, same discipline as `history.py`. We add our table
to the existing DB via `CREATE TABLE IF NOT EXISTS`, so history's rows are
never touched. Nothing leaves the machine.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime

from tuparles.history import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id    INTEGER PRIMARY KEY,
    ts    TEXT NOT NULL,
    name  TEXT NOT NULL,
    attrs TEXT NOT NULL DEFAULT '{}'
)
"""


def _conn() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    return conn


def write(name: str, attrs: dict) -> None:
    """Append one event. attrs is JSON-serialised; keep it small and flat."""
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    with closing(_conn()) as conn, conn:
        conn.execute(
            "INSERT INTO events (ts, name, attrs) VALUES (?, ?, ?)",
            (ts, name, json.dumps(attrs, ensure_ascii=False)),
        )


def read(
    name: str | None = None, limit: int | None = None
) -> list[tuple[str, str, dict]]:
    """Newest first: [(ts, name, attrs), …]. Filter by exact name if given."""
    sql = "SELECT ts, name, attrs FROM events"
    params: list = []
    if name is not None:
        sql += " WHERE name = ?"
        params.append(name)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with closing(_conn()) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(ts, n, json.loads(a)) for ts, n, a in rows]


def clear() -> int:
    """Wipe the event log (the 'forget my usage' action). Returns rows removed."""
    with closing(_conn()) as conn, conn:
        return conn.execute("DELETE FROM events").rowcount
