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
    args = parser.parse_args()

    if args.cmd == "history":
        from tuparles.history import recent, search

        rows = search(args.query, args.n) if args.query else recent(args.n)
        for ts, text in rows:
            print(f"[{ts}] {text}")
    elif args.cmd == "stats":
        _print_stats()
    else:
        from tuparles.daemon import run

        run()


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
        mix = ", ".join(
            f"{LANGUAGES.get(code, code)} ×{n}" for code, n in s["langs"]
        )
        print(f"Langues      {mix}")


if __name__ == "__main__":
    main()
