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
    args = parser.parse_args()

    if args.cmd == "history":
        from tuparles.history import recent, search

        rows = search(args.query, args.n) if args.query else recent(args.n)
        for ts, text in rows:
            print(f"[{ts}] {text}")
    else:
        from tuparles.daemon import run

        run()


if __name__ == "__main__":
    main()
