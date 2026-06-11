"""Entry point. Grows into the daemon launcher; for now, a sign of life."""

from tuparles import __version__


def main() -> None:
    print(f"TuParles {__version__} — le daemon arrive bientôt.")


if __name__ == "__main__":
    main()
