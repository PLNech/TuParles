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

# Telemetry columns, added by migration so pre-existing DBs keep working.
_META_COLUMNS = [
    ("audio_s", "REAL"),
    ("decode_s", "REAL"),
    ("deliver_s", "REAL"),
    ("chars", "INTEGER"),
    ("words", "INTEGER"),
    ("wpm", "REAL"),
    ("lang", "TEXT"),
    ("lang_prob", "REAL"),
]


def _db_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "tuparles" / "history.db"


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(dictations)")}
    for col, sql_type in _META_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE dictations ADD COLUMN {col} {sql_type}")
    return conn


def record(
    text: str,
    engine: str = "",
    audio_s: float | None = None,
    decode_s: float | None = None,
    deliver_s: float | None = None,
    lang: str | None = None,
    lang_prob: float | None = None,
) -> None:
    if not text:
        return
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    words = len(text.split())
    wpm = words / (audio_s / 60) if audio_s else None
    with closing(_conn()) as conn, conn:
        conn.execute(
            "INSERT INTO dictations (ts, text, engine, audio_s, decode_s,"
            " deliver_s, chars, words, wpm, lang, lang_prob)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                text,
                engine,
                audio_s,
                decode_s,
                deliver_s,
                len(text),
                words,
                wpm,
                lang,
                lang_prob,
            ),
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


def summarize() -> dict:
    """Aggregates for `tuparles stats` — everything stays on this machine."""
    with closing(_conn()) as conn:
        totals = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(audio_s), 0),"
            " COALESCE(SUM(words), 0), COALESCE(SUM(chars), 0),"
            " AVG(wpm), MIN(ts)"
            " FROM dictations"
        ).fetchone()
        speed = conn.execute(
            "SELECT AVG(audio_s / decode_s) FROM dictations"
            " WHERE decode_s > 0 AND audio_s > 0"
        ).fetchone()
        langs = conn.execute(
            "SELECT lang, COUNT(*) FROM dictations WHERE lang IS NOT NULL"
            " GROUP BY lang ORDER BY COUNT(*) DESC"
        ).fetchall()
    takes, audio_s, words, chars, avg_wpm, first_ts = totals
    return {
        "takes": takes,
        "audio_min": audio_s / 60,
        "words": words,
        "chars": chars,
        "avg_wpm": avg_wpm,
        "decode_x_realtime": speed[0],
        "langs": langs,
        "since": first_ts,
    }
