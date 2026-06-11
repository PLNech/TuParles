"""Deliver final text: type into the focused window, mirror to clipboard."""

import subprocess


def deliver(text: str) -> None:
    if not text:
        return
    _clipboard(text)
    _type_into_focus(text)


def _type_into_focus(text: str) -> None:
    # --clearmodifiers: the hotkey's Ctrl/Alt may still be held; without it
    # the typed keys would arrive as Ctrl+Alt+<char> chords.
    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", text],
        check=True,
        timeout=60,
    )


def _clipboard(text: str) -> None:
    subprocess.run(
        ["xsel", "--clipboard", "--input"],
        input=text.encode(),
        check=True,
        timeout=10,
    )
