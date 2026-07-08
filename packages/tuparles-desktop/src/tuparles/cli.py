"""Entry point: `tuparles` runs the daemon, `tuparles history` searches it."""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tuparles",
        description="Local push-to-talk dictation. No subcommand: start the daemon.",
    )
    sub = parser.add_subparsers(dest="cmd")
    hist = sub.add_parser("history", help="List or search past dictations")
    hist.add_argument("query", nargs="?", default="", help="substring to search")
    hist.add_argument("-n", type=int, default=20, help="max results")
    sub.add_parser("stats", help="Local dictation telemetry")
    voc = sub.add_parser(
        "vocab", help="Personal glossary: list, suggest from history, review, add"
    )
    voc.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "suggest", "review", "add"],
    )
    voc.add_argument("words", nargs="*", help="words to add (action: add)")
    voc.add_argument(
        "--min-count", type=int, default=2, help="suggest words seen ≥ N times"
    )
    rep = sub.add_parser(
        "report", help="Open a prefilled GitHub bug report (no account data sent)"
    )
    rep.add_argument("title", nargs="*", help="short summary of the issue")
    rep.add_argument("--no-open", action="store_true", help="just print the URL")
    sub.add_parser(
        "diag", help="Print this box's capability report (paste into a bug report)"
    )
    sub.add_parser("update", help="Check GitHub for a newer release (no token)")
    sub.add_parser("whatsnew", help="Show the latest changelog section")
    cs = sub.add_parser(
        "cheatsheet", help="Searchable list of voice commands & syntax phrases"
    )
    cs.add_argument(
        "query", nargs="?", default="", help="filter (accent/case-insensitive)"
    )
    onb = sub.add_parser(
        "onboarding", help="« Comment tu parles ? » — personnaliser (vue texte)"
    )
    onb.add_argument(
        "--replay", action="store_true", help="rejouer même si déjà configuré"
    )
    tr = sub.add_parser(
        "transcribe",
        help="Transcrire des fichiers audio/vidéo → <nom>-transcript.txt",
    )
    tr.add_argument("files", nargs="+", help="fichier(s) audio/vidéo (m4a, wav, mp3…)")
    tr.add_argument(
        "--force", action="store_true", help="écraser un transcript existant"
    )
    tr.add_argument(
        "--device",
        choices=["auto", "cuda", "cpu"],
        default="auto",
        help="silicium à utiliser (défaut : auto — GPU si dispo, sinon CPU)",
    )
    tr.add_argument("--model", help="forcer un modèle Whisper (ex. small, medium)")
    tr.add_argument(
        "--turn-gap",
        type=float,
        default=None,
        metavar="SECONDES",
        help="silence (s) marquant un changement de tour « — » "
        "(défaut : réglage turn_gap_s, 1.2 ; 0 = désactivé)",
    )
    tr.add_argument(
        "--no-json",
        action="store_true",
        help="ne pas écrire le sidecar JSON <nom>-transcript.json "
        "(défaut : réglage transcribe_json, activé)",
    )
    tr.add_argument(
        "--stdout", action="store_true", help="afficher aussi le transcript"
    )
    args = parser.parse_args()

    if args.cmd == "history":
        from tuparles.history import recent, search

        rows = search(args.query, args.n) if args.query else recent(args.n)
        for ts, text in rows:
            print(f"[{ts}] {text}")
    elif args.cmd == "stats":
        _print_stats()
    elif args.cmd == "vocab":
        _vocab(args)
    elif args.cmd == "report":
        _report(args)
    elif args.cmd == "diag":
        _diag()
    elif args.cmd == "update":
        _update()
    elif args.cmd == "whatsnew":
        _whatsnew()
    elif args.cmd == "cheatsheet":
        _cheatsheet(args)
    elif args.cmd == "onboarding":
        _onboarding(args)
    elif args.cmd == "transcribe":
        _transcribe(args)
    else:
        from tuparles.daemon import run

        run()


def _vocab(args) -> None:
    from tuparles import vocab
    from tuparles.config import VOCAB_FILE
    from tuparles.history import recent

    # The desktop tool keeps its historical repo-root vocab.txt: core vocab now
    # defaults to the config dir (portable), so the desktop path is passed in.
    if args.action == "add":
        added = vocab.add(args.words, VOCAB_FILE)
        print(f"Ajouté : {', '.join(added)}" if added else "Rien de nouveau.")
        return
    if args.action == "list":
        words = vocab.load(VOCAB_FILE)
        print(
            "\n".join(words) if words else "Glossaire vide — `tuparles vocab suggest`."
        )
        return

    # suggest / review share the mining pass over the whole local history.
    texts = [text for _ts, text in recent(1000)]
    existing = set(vocab.load(VOCAB_FILE))
    found = vocab.suggest(texts, existing, min_count=args.min_count)
    if not found:
        print("Aucun candidat — dicte encore un peu, le glossaire viendra.")
        return
    if args.action == "suggest":
        for word, n in found:
            print(f"{n:>4}×  {word}")
        print(f"\n{len(found)} candidats — `tuparles vocab review` pour trier.")
        return

    accepted: list[str] = []
    print(f"{len(found)} candidats. [o]ui / [N]on / [q]uitter")
    for word, n in found:
        try:
            answer = input(f"  {word}  (vu {n}×)  ? ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if answer == "q":
            break
        if answer in ("o", "y", "oui", "yes"):
            accepted.append(word)
    if accepted:
        vocab.add(accepted, VOCAB_FILE)
        print(f"Ajouté : {', '.join(accepted)} — actif dès la prochaine dictée.")
    else:
        print("Rien ajouté.")


def _diag() -> None:
    """Print the cross-env capability report + environment block — the exact
    thing a paste/focus bug report needs (#29). Copy-paste it into an issue, or
    use `tuparles report` to open a prefilled one."""
    from tuparles import capability
    from tuparles.bugreport import environment_block

    print(capability.probe().report(verbose=True))
    print()
    print(environment_block())


def _report(args) -> None:
    from tuparles.bugreport import issue_url

    title = " ".join(args.title).strip() or "Bug : "
    url = issue_url(title)
    print("Signaler un bug (le rapport s'ouvre dans ton navigateur, pré-rempli) :")
    print(url)
    if not args.no_open:
        import webbrowser

        webbrowser.open(url)


def _cheatsheet(args) -> None:
    from tuparles import cheatsheet

    print(cheatsheet.as_text(args.query))


def _onboarding(args) -> None:
    """The no-Qt view of « Comment tu parles ? » (#80).

    The graceful-degradation half of the onboarding pair: the same core the Qt
    carousel rides, rendered as a numbered terminal walkthrough so it works
    headless / on a minimal install. Each axis lists its choices with the *real*
    live preview beside them (so the terminal can't promise a style the engine
    wouldn't produce). Entrée = leave the setting untouched; q = stop and keep
    the rest as they are.
    """
    from tuparles import onboarding

    axes = onboarding.axes(force=args.replay)
    if not axes:
        print("Déjà configuré — `tuparles onboarding --replay` pour rejouer.")
        return

    print(
        "« Comment tu parles ? » — quelques réglages, modifiables après dans Réglages."
    )
    print("Entrée = ne rien changer · q = garder le reste tel quel.\n")
    chosen: dict[str, str] = {}
    for axis in axes:
        print(f"{axis.title} — {axis.question}")
        for i, choice in enumerate(axis.choices, 1):
            mark = "  (défaut)" if choice.value == axis.default else ""
            sample = onboarding.preview(axis.key, choice.value)
            print(f"  {i}. {choice.label:<14} {sample}{mark}")
        try:
            answer = input(f"  choix [1-{len(axis.choices)}] ? ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if answer == "q":
            break
        if not answer:
            continue  # blank = leave this axis untouched
        if answer.isdigit() and 1 <= int(answer) <= len(axis.choices):
            chosen[axis.key] = axis.choices[int(answer) - 1].value
        else:
            print("  (choix ignoré — inchangé)")
        print()

    onboarding.apply_choices(chosen)
    print("C'est noté. `tuparles onboarding --replay` pour recommencer.")


def _transcribe(args) -> None:
    """Offline file transcription (#…): each FILE → a sibling
    `<stem>-transcript.txt` of `[mm:ss] text` lines and (default on, `--no-json`
    to skip) a `<stem>-transcript.json` schema-v1 sidecar carrying the QC/word
    detail the txt drops. Never overwrites an existing sidecar without `--force`,
    and writes to NEW paths (never the input). Progress + model chatter go to
    stderr so `--stdout` stays clean."""
    import json
    import sys
    from datetime import date

    from tuparles import settings
    from tuparles.config import SAMPLE_RATE
    from tuparles.filetranscribe import (
        FileTranscriber,
        decode_to_pcm,
        format_ts,
        render_json,
        render_transcript,
    )

    want_json = bool(settings.get("transcribe_json")) and not args.no_json

    paths = [Path(p) for p in args.files]
    missing = [p for p in paths if not p.exists()]
    for p in missing:
        print(f"Introuvable : {p}", file=sys.stderr)
    if missing:
        return

    # Refuse to clobber a sidecar we didn't just make (implicit destruction is
    # still destruction). --force opts in per run. Each output is gated on its
    # own: if only the .txt exists we still write a missing .json (and vice
    # versa), so a file is decoded whenever any of its sidecars needs writing.
    def _wanted(out: Path) -> bool:
        if out.exists() and not args.force:
            print(f"Existe déjà (--force pour écraser) : {out}", file=sys.stderr)
            return False
        return True

    todo: list[tuple[Path, Path | None, Path | None]] = []
    for p in paths:
        txt_out = p.with_name(f"{p.stem}-transcript.txt")
        json_out = p.with_name(f"{p.stem}-transcript.json")
        do_txt = txt_out if _wanted(txt_out) else None
        do_json = (json_out if _wanted(json_out) else None) if want_json else None
        if do_txt or do_json:
            todo.append((p, do_txt, do_json))
    if not todo:
        return

    print("Chargement du modèle…", file=sys.stderr)
    tr = FileTranscriber(device=args.device, model=args.model)
    print(f"Modèle : {tr.model_name} ({tr.device})", file=sys.stderr)

    for p, txt_out, json_out in todo:
        print(f"Décodage audio : {p.name}", file=sys.stderr)
        pcm = decode_to_pcm(p)
        total = len(pcm) / SAMPLE_RATE

        def progress(end_s: float, _total: float = total, _name: str = p.name) -> None:
            pct = min(100, int(100 * end_s / _total)) if _total else 0
            print(f"\r  {_name} : {pct:3d}%", end="", file=sys.stderr, flush=True)

        segments, info = tr.transcribe(pcm, progress=progress)
        print("", file=sys.stderr)
        today = date.today().isoformat()
        written: list[Path] = []
        text = render_transcript(
            segments,
            source=p.name,
            model=tr.model_name,
            device=tr.device,
            duration=total,
            date=today,
            turn_gap=args.turn_gap,  # None → the turn_gap_s setting (1.2 default)
        )
        if txt_out is not None:
            txt_out.write_text(text, encoding="utf-8")
            written.append(txt_out)
        if json_out is not None:
            data = render_json(
                segments,
                source=p.name,
                model=tr.model_name,
                device=tr.device,
                duration=total,
                date=today,
                language=getattr(info, "language", None),
                turn_gap=args.turn_gap,
            )
            json_out.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            written.append(json_out)
        summary = " + ".join(str(w) for w in written)
        print(f"✓ {summary}  ({len(segments)} segments · {format_ts(total)})")
        if args.stdout:
            print(text)


def _whatsnew() -> None:
    from tuparles import whatsnew

    text = whatsnew._changelog_text()
    section = whatsnew.latest_section(text) if text else None
    print(section or "Pas de notes de version trouvées.")
    whatsnew.mark_seen()  # seeing it manually counts as seen


def _update() -> None:
    from tuparles.update_check import check

    info = check()
    if info is None:
        print("Impossible de vérifier les mises à jour (hors-ligne ?).")
        return
    if info.available:
        print(f"Nouvelle version : {info.latest} (tu as {info.current})")
        print(info.url)
    else:
        print(f"À jour : {info.current} est la dernière version.")


def _print_stats() -> None:
    from tuparles.history import summarize
    from tuparles.languages import LANGUAGES

    s = summarize()
    if not s["takes"]:
        print("Aucune dictée enregistrée — parle d'abord, compte ensuite.")
        return
    print(f"Dictées      {s['takes']}  (depuis {s['since'][:10]})")
    print(f"Audio        {s['audio_min']:.1f} min")
    print(f"Mots         {s['words']}  ({s['chars']} caractères)")
    if s["avg_wpm"]:
        print(f"Débit        {s['avg_wpm']:.0f} mots/min en moyenne")
    if s["decode_x_realtime"]:
        print(f"Décodage     {s['decode_x_realtime']:.0f}x temps réel")
    if s["langs"]:
        mix = ", ".join(f"{LANGUAGES.get(code, code)} ×{n}" for code, n in s["langs"])
        print(f"Langues      {mix}")


if __name__ == "__main__":
    main()
