"""Entry point: `tuparles` runs the daemon, `tuparles history` searches it."""

import argparse


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
    else:
        from tuparles.daemon import run

        run()


def _vocab(args) -> None:
    from tuparles import vocab
    from tuparles.history import recent

    if args.action == "add":
        added = vocab.add(args.words)
        print(f"Ajouté : {', '.join(added)}" if added else "Rien de nouveau.")
        return
    if args.action == "list":
        words = vocab.load()
        print(
            "\n".join(words) if words else "Glossaire vide — `tuparles vocab suggest`."
        )
        return

    # suggest / review share the mining pass over the whole local history.
    texts = [text for _ts, text in recent(1000)]
    existing = set(vocab.load())
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
        vocab.add(accepted)
        print(f"Ajouté : {', '.join(accepted)} — actif dès la prochaine dictée.")
    else:
        print("Rien ajouté.")


def _report(args) -> None:
    from tuparles.bugreport import issue_url

    title = " ".join(args.title).strip() or "Bug : "
    url = issue_url(title)
    print("Signaler un bug (le rapport s'ouvre dans ton navigateur, pré-rempli) :")
    print(url)
    if not args.no_open:
        import webbrowser

        webbrowser.open(url)


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
