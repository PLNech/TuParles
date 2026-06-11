"""Entry point: `tuparles` starts the dictation daemon."""


def main() -> None:
    from tuparles.daemon import run

    run()


if __name__ == "__main__":
    main()
