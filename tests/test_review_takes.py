"""Consent-review loop + share_ok schema. Hermetic: a tmp XDG_DATA_HOME isolates
the history DB and the takes/misses tree, so we never touch the user's real store.
"""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tuparles import history, takes

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_takes.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("review_takes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # register before exec: @dataclass with `from __future__ import annotations`
    # resolves field types via sys.modules[cls.__module__].
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


review = _load_script()


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


def _scripted(keys):
    """An `ask` that returns queued keys, then raises EOFError (simulates Ctrl-D)."""
    it = iter(keys)

    def ask(_prompt):
        try:
            return next(it)
        except StopIteration as exc:
            raise EOFError from exc

    return ask


def _take(row_id=1, text="bonjour le monde", wav=None):
    return review.Take(
        id=row_id,
        ts="2026-07-08",
        lang="fr",
        engine="GpuEngine",
        audio_s=1.2,
        text=text,
        wav=wav,
    )


# --- schema / helpers -------------------------------------------------------


class TestSchema:
    def test_migration_adds_share_ok_without_data_loss(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        path = tmp_path / "tuparles" / "history.db"
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE dictations (id INTEGER PRIMARY KEY,"
                " ts TEXT NOT NULL, text TEXT NOT NULL,"
                " engine TEXT NOT NULL DEFAULT '')"
            )
            conn.execute(
                "INSERT INTO dictations (ts, text) VALUES ('2026-01-01', 'ancien')"
            )
        # opening via any helper triggers the migration
        assert history.shared_rows() == []  # column now exists, nothing flagged yet
        assert [t for _, t in history.recent(5)] == ["ancien"]  # old row survived
        cols = {
            r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(dictations)")
        }
        assert "share_ok" in cols

    def test_default_is_unreviewed_null(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        rid = history.record("pas encore relu")
        with sqlite3.connect(history.db_path()) as conn:
            (val,) = conn.execute(
                "SELECT share_ok FROM dictations WHERE id = ?", (rid,)
            ).fetchone()
        assert val is None  # NULL = unreviewed, the assistant's default "no"

    def test_set_share_ok_and_shared_rows_roundtrip(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        a = history.record("premier", lang="fr")
        b = history.record("second", lang="en")
        c = history.record("privé", lang="fr")
        history.set_share_ok(a, True)
        history.set_share_ok(b, True)
        history.set_share_ok(c, False)
        rows = history.shared_rows()
        # newest-first, only the two flagged OK, shape (id, ts, lang, text)
        assert [r[0] for r in rows] == [b, a]
        assert rows[0][2] == "en" and rows[0][3] == "second"
        assert all(len(r) == 4 for r in rows)
        # private row is absent by construction
        assert c not in [r[0] for r in rows]

    def test_shared_rows_limit(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        for i in range(5):
            rid = history.record(f"take {i}")
            history.set_share_ok(rid, True)
        assert len(history.shared_rows(limit=2)) == 2

    def test_set_share_ok_is_reversible(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        rid = history.record("je change d'avis")
        history.set_share_ok(rid, True)
        assert [r[0] for r in history.shared_rows()] == [rid]
        history.set_share_ok(rid, False)
        assert history.shared_rows() == []


# --- review loop core -------------------------------------------------------


class TestReviewLoop:
    def test_o_x_skip_decisions(self):
        applied = []
        items = [_take(1), _take(2), _take(3)]
        tally = review.review_items(
            items,
            ask=_scripted(["o", "x", ""]),
            play=lambda t: None,
            apply=lambda t, ok: applied.append((t.id, ok)),
        )
        assert tally == {"ok": 1, "private": 1, "skipped": 1}
        assert applied == [(1, True), (2, False)]  # skip applies nothing

    def test_replay_then_decide(self):
        played = []
        applied = []
        wav = Path("/tmp/nope.wav")
        tally = review.review_items(
            [_take(7, wav=wav)],
            ask=_scripted(["r", "o"]),
            play=lambda t: played.append(t.id),
            apply=lambda t, ok: applied.append((t.id, ok)),
        )
        assert played == [7]  # 'r' replayed without consuming the decision
        assert applied == [(7, True)]
        assert tally["ok"] == 1

    def test_all_remaining_confirmed_grants_rest(self):
        applied = []
        items = [_take(1), _take(2), _take(3)]
        tally = review.review_items(
            items,
            ask=_scripted(["a", "y"]),  # confirm on the first, rest auto-granted
            play=lambda t: None,
            apply=lambda t, ok: applied.append((t.id, ok)),
        )
        assert tally == {"ok": 3, "private": 0, "skipped": 0}
        assert applied == [(1, True), (2, True), (3, True)]

    def test_all_remaining_declined_reprompts(self):
        applied = []
        tally = review.review_items(
            [_take(1), _take(2)],
            ask=_scripted(["a", "n", "x", "o"]),  # decline → x row1, o row2
            play=lambda t: None,
            apply=lambda t, ok: applied.append((t.id, ok)),
        )
        assert applied == [(1, False), (2, True)]
        assert tally == {"ok": 1, "private": 1, "skipped": 0}

    def test_quit_leaves_remaining_untouched(self):
        applied = []
        tally = review.review_items(
            [_take(1), _take(2), _take(3)],
            ask=_scripted(["o", "q"]),
            play=lambda t: None,
            apply=lambda t, ok: applied.append((t.id, ok)),
        )
        assert applied == [(1, True)]  # row 2 quit before deciding, row 3 never seen
        assert tally == {"ok": 1, "private": 0, "skipped": 0}

    def test_eof_quits_gracefully(self):
        tally = review.review_items(
            [_take(1)],
            ask=_scripted([]),  # immediate EOF
            play=lambda t: None,
            apply=lambda t, ok: (_ for _ in ()).throw(AssertionError("no apply")),
        )
        assert tally == {"ok": 0, "private": 0, "skipped": 0}

    def test_unrecognised_key_reprompts(self):
        applied = []
        tally = review.review_items(
            [_take(1)],
            ask=_scripted(["?", "z", "o"]),
            play=lambda t: None,
            apply=lambda t, ok: applied.append((t.id, ok)),
        )
        assert applied == [(1, True)]
        assert tally["ok"] == 1


class TestReviewAppliesToDb:
    """The DB adapter really persists decisions via history.set_share_ok."""

    def test_decisions_land_in_share_ok(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        a = history.record("oui")
        b = history.record("non")
        items = review._rows_to_review(redo=False, wav_only=False, limit=None)
        assert [t.id for t in items] == [a, b]  # oldest-first, both unreviewed
        review.review_items(
            items,
            ask=_scripted(["o", "x"]),
            play=lambda t: None,
            apply=review._apply_row,
        )
        assert [r[0] for r in history.shared_rows()] == [a]
        # b is now private, so no longer unreviewed
        again = review._rows_to_review(redo=False, wav_only=False, limit=None)
        assert again == []


class TestRowSelection:
    def test_wav_only_filters(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        a = history.record("avec wav")
        history.record("sans wav")
        takes.takes_dir().mkdir(parents=True, exist_ok=True)
        (takes.takes_dir() / f"{a}.wav").write_bytes(b"RIFF")
        items = review._rows_to_review(redo=False, wav_only=True, limit=None)
        assert [t.id for t in items] == [a]
        assert items[0].wav is not None

    def test_redo_includes_reviewed(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        a = history.record("déjà relu")
        history.set_share_ok(a, True)
        assert review._rows_to_review(False, False, None) == []
        assert [t.id for t in review._rows_to_review(True, False, None)] == [a]

    def test_limit_caps_batch(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        for _ in range(4):
            history.record("x")
        assert len(review._rows_to_review(False, False, 2)) == 2


# --- misses consent sidecar -------------------------------------------------


class TestMissConsent:
    def test_write_is_additive_and_leaves_no_tmp(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        review.set_miss_consent("miss-a.wav", True)
        review.set_miss_consent("miss-b.wav", False)
        path = takes.misses_dir() / "consent.json"
        data = json.loads(path.read_text())
        assert data == {"miss-a.wav": True, "miss-b.wav": False}  # both kept
        # atomic write cleaned its tmp up after itself
        assert not (takes.misses_dir() / "consent.json.tmp").exists()

    def test_overwrite_updates_in_place(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        review.set_miss_consent("miss-a.wav", False)
        review.set_miss_consent("miss-a.wav", True)  # changed my mind
        data = json.loads((takes.misses_dir() / "consent.json").read_text())
        assert data == {"miss-a.wav": True}

    def test_corrupt_sidecar_is_ignored_not_crashing(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        takes.misses_dir().mkdir(parents=True, exist_ok=True)
        (takes.misses_dir() / "consent.json").write_text("{ not json")
        review.set_miss_consent("miss-a.wav", True)  # recovers, does not raise
        data = json.loads((takes.misses_dir() / "consent.json").read_text())
        assert data == {"miss-a.wav": True}

    def test_misses_to_review_skips_consented(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        takes.misses_dir().mkdir(parents=True, exist_ok=True)
        for name in ("miss-1.wav", "miss-2.wav"):
            (takes.misses_dir() / name).write_bytes(b"RIFF")
        review.set_miss_consent("miss-1.wav", True)
        pending = review._misses_to_review(redo=False, limit=None)
        assert [t.wav.name for t in pending] == ["miss-2.wav"]
        # --redo brings the decided one back
        allm = review._misses_to_review(redo=True, limit=None)
        assert {t.wav.name for t in allm} == {"miss-1.wav", "miss-2.wav"}

    def test_miss_apply_adapter_persists(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        takes.misses_dir().mkdir(parents=True, exist_ok=True)
        (takes.misses_dir() / "miss-9.wav").write_bytes(b"RIFF")
        [item] = review._misses_to_review(redo=True, limit=None)
        review.review_items(
            [item],
            ask=_scripted(["o"]),
            play=lambda t: None,
            apply=review._apply_miss,
        )
        data = json.loads((takes.misses_dir() / "consent.json").read_text())
        assert data == {"miss-9.wav": True}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
