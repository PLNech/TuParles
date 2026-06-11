"""Deliver final text: type into the focused window, mirror to clipboard."""

import subprocess


def deliver(text: str) -> None:
    if not text:
        return
    to_clipboard(text)
    _type_into_focus(text)


def _type_into_focus(text: str) -> None:
    # --clearmodifiers: the hotkey's Ctrl/Alt may still be held; without it
    # the typed keys would arrive as Ctrl+Alt+<char> chords.
    # Low delay: long transcripts at high per-key delay flood X with synthetic
    # events for seconds and make the focused app feel frozen.
    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--delay", "2", "--", text],
        check=True,
        timeout=60,
    )


def to_clipboard(text: str) -> None:
    subprocess.run(
        ["xsel", "--clipboard", "--input"],
        input=text.encode(),
        check=True,
        timeout=10,
    )
