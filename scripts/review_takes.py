#!/usr/bin/env python3
"""Consent review: you decide, take by take, what the assistant may read.

The dev capture (``takes.py``) keeps *your* speech on disk — the transcript in the
history DB, and (when ``TUPARLES_DEV`` is set) the raw ``takes/<id>.wav``. That is
yours. Before any AI assistant looks at a single word of it for forensics, you
grant it here, one take at a time: ``o`` shares it, ``x`` keeps it private, Enter
leaves it unreviewed. The grant is a ``share_ok`` flag on the row (see
``history.set_share_ok`` / ``history.shared_rows``); it stays on this machine and
NEVER authorises committing the speech to the (public) git repo. Flagged-OK means
local-assistant-eyes only.

Reviewing your own speech means *seeing* it — so this tool prints the transcript.
That is the point: you can't consent to sharing what you can't read.

Run::

    poetry run python scripts/review_takes.py            # unreviewed rows, oldest first
    poetry run python scripts/review_takes.py --redo     # revisit already-decided rows
    poetry run python scripts/review_takes.py --wav-only  # only rows with a WAV
    poetry run python scripts/review_takes.py --misses    # the empty-decode WAVs (no DB row)
    poetry run python scripts/review_takes.py --list-shared   # what the assistant will read
    poetry run python scripts/review_takes.py --stats     # counts, then exit

This writes only under the XDG data store (the history DB and, for misses, a
``misses/consent.json`` sidecar) — never anything under the repo.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tuparles import history, takes

# --- data ------------------------------------------------------------------


@dataclass
class Take:
    """One reviewable item — a history row (``id`` set) or a miss (``id`` None)."""

    id: int | None
    ts: str
    lang: str
    engine: str
    audio_s: float | None
    text: str
    wav: Path | None
    # The last painted partial + the quiet-take-rescue verdict (2026-07-15).
    # Same speech as `text`, so reviewing/consenting covers both — you can't
    # consent to sharing what you can't read, hence it's displayed too.
    partial: str | None = None
    rescued: int | None = None  # NULL didn't fire / 0 kept original / 1 adopted


AskFn = Callable[[str], str]
PlayFn = Callable[["Take"], None]
ApplyFn = Callable[["Take", bool], None]


# --- DB access -------------------------------------------------------------


def _connect():
    """A migrated connection. ``history._conn()`` runs the schema + column
    migrations (including ``share_ok``), so reviewing a DB written before this
    feature existed Just Works — we reuse it rather than re-implement the PRAGMA
    dance and risk drift."""
    return history._conn()


def _rows_to_review(redo: bool, wav_only: bool, limit: int | None) -> list[Take]:
    """Rows to review, oldest first (chronological is how you remember dictating
    them). Default: only the unreviewed (``share_ok IS NULL``); ``--redo`` widens
    to everything so you can change your mind."""
    where = "" if redo else " WHERE share_ok IS NULL"
    from contextlib import closing

    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, ts, lang, engine, audio_s, text, partial, rescued"
            " FROM dictations" + where + " ORDER BY id ASC"
        ).fetchall()
    takes_dir = takes.takes_dir()
    out: list[Take] = []
    for row_id, ts, lang, engine, audio_s, text, partial, rescued in rows:
        wav = takes_dir / f"{row_id}.wav"
        wav = wav if wav.exists() else None
        if wav_only and wav is None:
            continue
        out.append(
            Take(
                id=row_id,
                ts=ts or "",
                lang=lang or "?",
                engine=engine or "",
                audio_s=audio_s,
                text=text,
                wav=wav,
                partial=partial,
                rescued=rescued,
            )
        )
    if limit is not None:
        out = out[:limit]
    return out


# --- consent sidecar for misses (no DB row to hang a flag on) --------------


def _consent_path() -> Path:
    return takes.misses_dir() / "consent.json"


def _load_consent() -> dict[str, bool]:
    path = _consent_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): bool(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _save_consent(mapping: dict[str, bool]) -> None:
    """Write the filename→bool consent map atomically (tmp + rename) so a Ctrl-C
    mid-write can never leave a half-JSON that loses every prior decision."""
    path = _consent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mapping, indent=2, sort_keys=True))
    os.replace(tmp, path)  # atomic on POSIX


def set_miss_consent(filename: str, ok: bool) -> None:
    """Record one miss's decision, additively — merge into the existing map so we
    never clobber earlier grants (never moves or deletes the WAV itself)."""
    mapping = _load_consent()
    mapping[filename] = ok
    _save_consent(mapping)


def _misses_to_review(redo: bool, limit: int | None) -> list[Take]:
    consent = _load_consent()
    wavs = sorted(takes.misses_dir().glob("*.wav"), key=lambda p: p.name)
    out: list[Take] = []
    for wav in wavs:
        if not redo and wav.name in consent:
            continue
        out.append(
            Take(
                id=None,
                ts=wav.name,
                lang="?",
                engine="",
                audio_s=None,
                text="(empty decode — no transcript; audio only)",
                wav=wav,
            )
        )
    if limit is not None:
        out = out[:limit]
    return out


# --- audio -----------------------------------------------------------------


def play_wav(take: Take) -> None:
    """Play the take's WAV via ``paplay`` (PulseAudio), falling back to ``aplay``
    (ALSA). Interactive and blocking on purpose — you listen, then you decide."""
    if take.wav is None:
        print("  (no audio for this take — text-only review)")
        return
    for player in ("paplay", "aplay"):
        try:
            subprocess.run([player, str(take.wav)], check=False)
            return
        except FileNotFoundError:
            continue
    print("  (no paplay/aplay found — install pulseaudio-utils or alsa-utils)")


# --- the review loop -------------------------------------------------------

_MENU = "  [o]k  [x] private  ⏎ skip  [r]eplay  [a]ll-remaining-ok  [q]uit > "


def _describe(take: Take) -> None:
    who = f"#{take.id}" if take.id is not None else take.ts
    dur = f"{take.audio_s:.1f}s" if take.audio_s is not None else "?s"
    rescue = {0: "  [rescue: kept original]", 1: "  [rescue: adopted]"}.get(
        take.rescued, ""
    )
    head = f"\n─── {who}  {take.ts}  [{take.lang}]  {take.engine}  {dur}{rescue}"
    print(head)
    print(f"    {take.text}")
    # The stored partial is the same speech under the same consent — show it so
    # the grant covers everything the row actually holds.
    if take.partial and take.partial != take.text:
        print(f"    (aperçu) {take.partial}")
    if take.wav is not None:
        print(f"    ♪ {take.wav.name} present — 'r' to play")


def review_items(
    items: list[Take],
    *,
    ask: AskFn,
    play: PlayFn,
    apply: ApplyFn,
) -> dict[str, int]:
    """Pure-ish review core: prompt each item, apply the decision, tally.

    ``ask(prompt) -> key``, ``play(take)``, ``apply(take, ok)`` are all injected
    so the daemon-free test can script keystrokes and assert decisions without a
    terminal or a sound card. EOF/Ctrl-C from ``ask`` quits gracefully (returns
    the tally so far). ``a`` grants the current item and every remaining one after
    a ``y/N`` confirm.
    """
    tally = {"ok": 0, "private": 0, "skipped": 0}
    grant_all = False
    for take in items:
        _describe(take)
        if grant_all:
            apply(take, True)
            tally["ok"] += 1
            continue
        while True:
            try:
                key = ask(_MENU).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n(quit)")
                return tally
            if key == "r":
                play(take)
                continue
            if key == "o":
                apply(take, True)
                tally["ok"] += 1
                break
            if key == "x":
                apply(take, False)
                tally["private"] += 1
                break
            if key == "":
                tally["skipped"] += 1
                break
            if key == "a":
                try:
                    confirm = ask("  grant ALL remaining takes? [y/N] > ")
                except (EOFError, KeyboardInterrupt):
                    print("\n(quit)")
                    return tally
                if confirm.strip().lower() == "y":
                    grant_all = True
                    apply(take, True)
                    tally["ok"] += 1
                    break
                continue  # not confirmed → re-prompt this same take
            if key == "q":
                return tally
            print("  ? unrecognised — o / x / Enter / r / a / q")
    return tally


# --- apply adapters --------------------------------------------------------


def _apply_row(take: Take, ok: bool) -> None:
    assert take.id is not None
    history.set_share_ok(take.id, ok)


def _apply_miss(take: Take, ok: bool) -> None:
    assert take.wav is not None
    set_miss_consent(take.wav.name, ok)


# --- top-level modes -------------------------------------------------------


def _stats() -> None:
    from contextlib import closing

    with closing(_connect()) as conn:
        counts = dict(
            conn.execute(
                "SELECT COALESCE(share_ok, -1), COUNT(*) FROM dictations GROUP BY 1"
            ).fetchall()
        )
    unreviewed = counts.get(-1, 0)
    ok = counts.get(1, 0)
    private = counts.get(0, 0)
    consent = _load_consent()
    n_miss_wav = len(list(takes.misses_dir().glob("*.wav")))
    print(f"unreviewed : {unreviewed}")
    print(f"ok (shared): {ok}")
    print(f"private    : {private}")
    print(
        f"misses     : {n_miss_wav} wav "
        f"({sum(consent.values())} ok / "
        f"{sum(1 for v in consent.values() if not v)} private / "
        f"{max(0, n_miss_wav - len(consent))} unreviewed)"
    )


def _list_shared() -> None:
    for row_id, ts, lang, text in history.shared_rows():
        print(f"{row_id}\t{ts}\t{lang or '?'}\t{text}")


def _prompt_stdin(prompt: str) -> str:
    return input(prompt)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--redo",
        action="store_true",
        help="include already-reviewed items (to change your mind)",
    )
    ap.add_argument(
        "--wav-only",
        action="store_true",
        help="only rows that have a captured WAV",
    )
    ap.add_argument("-n", type=int, default=None, dest="limit", help="cap the batch")
    ap.add_argument(
        "--misses",
        action="store_true",
        help="review the empty-decode WAVs (consent stored in misses/consent.json)",
    )
    ap.add_argument(
        "--list-shared",
        action="store_true",
        help="print flagged-OK rows (id\\tts\\tlang\\ttext) and exit",
    )
    ap.add_argument("--stats", action="store_true", help="print counts and exit")
    args = ap.parse_args(argv)

    if args.list_shared:
        _list_shared()
        return
    if args.stats:
        _stats()
        return

    if args.misses:
        items = _misses_to_review(args.redo, args.limit)
        apply: ApplyFn = _apply_miss
        empty_msg = f"no misses to review in {takes.misses_dir()}."
    else:
        items = _rows_to_review(args.redo, args.wav_only, args.limit)
        apply = _apply_row
        empty_msg = "nothing to review — all decided (use --redo to revisit)."

    if not items:
        print(empty_msg)
        return

    print(f"reviewing {len(items)} item(s) — your speech, your call.")
    tally = review_items(items, ask=_prompt_stdin, play=play_wav, apply=apply)
    print(
        f"\n── done: {tally['ok']} shared, {tally['private']} private, "
        f"{tally['skipped']} skipped this session."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(quit)")
        sys.exit(0)
