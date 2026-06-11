"""Deliver final text: type into the focused window, mirror to clipboard."""

import subprocess

# Every modifier the stop-tap (RCtrl+RAlt/AltGr) or a hasty hand might hold
# when typing starts. Released explicitly *before* typing instead of using
# xdotool --clearmodifiers: that flag re-presses the modifiers afterward even
# if the user physically released them mid-type (jordansissel/xdotool#43),
# leaving phantom stuck Ctrl/Alt/AltGr — the "keyboard locked" bug. A keyup
# on an already-released key is a no-op, so this list errs generous.
_MODIFIERS = [
    "Control_L", "Control_R",
    "Alt_L", "Alt_R", "ISO_Level3_Shift",
    "Shift_L", "Shift_R",
    "Super_L", "Super_R",
]


def deliver(text: str) -> None:
    if not text:
        return
    to_clipboard(text)
    _type_into_focus(text)


# Above this, char-by-char typing takes whole seconds (10 ms/char) and the
# focused app feels frozen — paste instead. Below it, typing is sub-2s and
# works everywhere, including paste-hostile fields.
PASTE_THRESHOLD_CHARS = 200

# Window classes that want Ctrl+Shift+V (Ctrl+V is a control char in a tty).
_TERMINALS = {
    "gnome-terminal-server", "org.gnome.terminal", "kgx",
    "alacritty", "kitty", "konsole", "xterm", "terminator", "tilix",
    "st", "urxvt", "wezterm", "ghostty",
}


def _is_terminal(wm_class: str) -> bool:
    return wm_class.strip().casefold() in _TERMINALS


def _type_into_focus(text: str) -> None:
    subprocess.run(
        ["xdotool", "keyup", *_MODIFIERS], check=False, timeout=5
    )
    if len(text) > PASTE_THRESHOLD_CHARS:
        try:
            _paste_into_focus()
            return
        except Exception:
            pass  # unknown window class etc. — fall back to typing
    # delay 10: at 2 ms, ibus/app input queues drop and reorder chars under
    # load ("l'application et" landed as "l'applicat ionet" while the history
    # DB held the correct text). The old "frozen keyboard" complaint that
    # motivated delay 2 was the stuck-modifier bug above, not the delay.
    subprocess.run(
        ["xdotool", "type", "--delay", "10", "--", text],
        check=True,
        timeout=120,
    )


def _paste_into_focus() -> None:
    """The clipboard already holds the text (deliver() set it first)."""
    wm_class = subprocess.run(
        ["xdotool", "getactivewindow", "getwindowclassname"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    ).stdout
    combo = "ctrl+shift+v" if _is_terminal(wm_class) else "ctrl+v"
    subprocess.run(["xdotool", "key", combo], check=True, timeout=5)


def to_clipboard(text: str) -> None:
    subprocess.run(
        ["xsel", "--clipboard", "--input"],
        input=text.encode(),
        check=True,
        timeout=10,
    )
