"""Deliver final text: type into the focused window, mirror to clipboard.

On X11, xdotool types short ASCII and pastes the rest. On Wayland there is
no xdotool: everything goes through the clipboard (wl-copy) and a Ctrl+V
sent by ydotool's uinput keyboard. Typing is never attempted there —
ydotool assumes a US keymap, so on an azerty layout `a` lands as `q`."""

import shutil
import string
import subprocess
import time

from tuparles.config import IS_WAYLAND as _WAYLAND

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


def deliver(text: str, focus_class: str = "", before_paste=None) -> None:
    if not text:
        return
    t0 = time.monotonic()
    to_clipboard(text)
    t1 = time.monotonic()
    _type_into_focus(text, focus_class, before_paste)
    t2 = time.monotonic()
    # Pastes have clocked at ~3 s where ~0.3 s is expected — when delivery
    # drags, say which leg (clipboard vs xdotool) so the journal can tell.
    if t2 - t0 > 1.0:
        print(
            f"deliver slow: clipboard {t1 - t0:.1f}s, "
            f"focus-injection {t2 - t1:.1f}s ({len(text)} chars)"
        )


# Above this, char-by-char typing takes whole seconds (10 ms/char) and the
# focused app feels frozen — paste instead. Below it, typing is sub-2s and
# works everywhere, including paste-hostile fields.
PASTE_THRESHOLD_CHARS = 200

# Printable ASCII exists on every layout in the user's switcher (us and fr
# alike). Anything beyond it can be MISSING from the active layout — é/à on
# QWERTY — and xdotool then remaps a scratch keycode per occurrence. Each
# remap broadcasts MappingNotify to every X client and gnome-shell re-grabs
# all its keybindings in response: a short accented take froze the whole
# desktop (Super/expose included) for ~30 s. Such text always goes through
# the clipboard instead — paste is layout-blind.
_KEYMAP_SAFE = set(string.printable)


def _should_paste(text: str) -> bool:
    return len(text) > PASTE_THRESHOLD_CHARS or any(
        c not in _KEYMAP_SAFE for c in text
    )

# Window classes that want Ctrl+Shift+V (Ctrl+V is a control char in a tty).
# "gnome-terminal" covers the res_class form ("Gnome-terminal"); the
# -server form is the instance — Wayland reports whichever, so list both.
_TERMINALS = {
    "gnome-terminal-server", "gnome-terminal", "org.gnome.terminal",
    "kgx", "org.gnome.console",
    "alacritty", "kitty", "konsole", "xterm", "terminator", "tilix",
    "st", "urxvt", "wezterm", "ghostty",
}


def _is_terminal(wm_class: str) -> bool:
    return wm_class.strip().casefold() in _TERMINALS


def _paste_combo(is_terminal: bool) -> str:
    # Terminals read Ctrl+V as a literal control char; they paste on
    # Ctrl+Shift+V. Both delivery backends pick the combo through here.
    return "ctrl+shift+v" if is_terminal else "ctrl+v"


# The focuswindow@tuparles.local GNOME extension publishes the focused
# window's class here — Wayland's only way for a client to read it.
_FOCUS_DEST = "org.tuparles.FocusWindow"
_FOCUS_PATH = "/org/tuparles/FocusWindow"


def _focus_wm_class(timeout: float = 2.0) -> str:
    """'class|instance' of the focused window from the GNOME extension, or
    '' if it isn't installed/enabled (older sessions, KDE, …). Quiet and
    fast: a short cap so a missing or busy service never stalls delivery."""
    try:
        proc = subprocess.run(
            ["gdbus", "call", "--session",
             "--dest", _FOCUS_DEST,
             "--object-path", _FOCUS_PATH,
             "--method", f"{_FOCUS_DEST}.GetClass"],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    # gdbus prints a GVariant tuple, e.g.  ('Gnome-terminal|gnome-terminal-server',)
    return proc.stdout.strip().lstrip("(").rstrip(")").rstrip(",").strip("'\"")


def _pair_is_terminal(wm_class: str) -> bool:
    # "class|instance" (X11 reports just one token) → does either half name a
    # known terminal? Shared by the live gdbus reply and a class captured at
    # record-start.
    return any(_is_terminal(part) for part in wm_class.split("|") if part)


def _focus_is_terminal() -> bool:
    return _pair_is_terminal(_focus_wm_class())


def capture_focus_class() -> str:
    """The focused window's class, read the moment a take STARTS — the target
    window is reliably focused then, before the bubble appears and gnome-shell
    starts animating. Querying instead at delivery time raced that animation:
    gdbus returned '' under load, delivery fell back to plain Ctrl+V, and a
    terminal silently swallowed it (Ctrl+V is a control char there, not paste)
    — the "nothing pasted" bug. '' if unreadable; delivery then re-queries
    live (after the bubble is hidden) as a fallback.

    Wayland-only: the daemon gates this behind IS_WAYLAND. X11 never steals
    focus with its bubble, so it keeps reading focus live at delivery and has
    no need for a start-time snapshot. The cap is short because this runs on
    the GUI thread at take-start — a stalled gnome-shell must not freeze it
    (it's calm then, so the call is normally a few ms)."""
    return _focus_wm_class(timeout=0.5)


def _wayland_paste(focus_class: str = "", before_paste=None) -> None:
    """The clipboard already holds the text (deliver() set it first).

    Ubuntu ships ydotool 0.1.8: no ydotoold, so each call creates its own
    uinput keyboard (needs the udev rule from scripts/setup_wayland.sh).
    The --delay gives the compositor time to recognize that new device
    before keys fire; it also doubles as stuck-modifier insurance — by
    then the stop-tap fingers have lifted, and 0.1.8 can't send bare
    key-ups anyway (sequences only).

    Terminal vs app comes from `focus_class` (captured when the take started)
    when given, else a live read of the GNOME focus-window extension. With no
    class and no extension we fall back to Ctrl+V (the pre-extension
    behaviour), and a terminal then still needs a manual Ctrl+Shift+V.

    `before_paste`, if given, runs FIRST: the daemon hides the focus-stealing
    bubble there, so the paste lands in the user's window and not the bubble
    (Mutter ignores the bubble's no-focus hints — see capture_focus_class).
    Running it before the terminal decision also lets the live fallback below
    (used only when no class was captured) read the real target's focus, not
    the bubble's. Best-effort: a hide that throws must not abort a take whose
    text is already on the clipboard. ydotool's --delay covers the moment
    Mutter needs to hand focus back to the target.
    """
    if shutil.which("ydotool") is None:
        print("ydotool absent — transcript au presse-papiers, colle avec Ctrl+V")
        return
    if before_paste is not None:
        try:
            before_paste()
        except Exception:
            pass
    is_terminal = (
        _pair_is_terminal(focus_class) if focus_class else _focus_is_terminal()
    )
    combo = _paste_combo(is_terminal)
    # Best-effort like the X11 paste: the clipboard already holds the text,
    # so a ydotool nonzero exit or timeout must NOT raise — that would make
    # deliver() report a correctly-transcribed take as failed and skip
    # history. A missed paste just leaves the text one manual paste away.
    try:
        subprocess.run(
            ["ydotool", "key", "--delay", "200", combo],
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        # OSError too: ydotool could vanish between the which() check and here.
        # Delivery must never raise — the clipboard already holds the text.
        pass
    print(f"paste (wayland): {combo}")


def _type_into_focus(text: str, focus_class: str = "", before_paste=None) -> None:
    if _WAYLAND:
        _wayland_paste(focus_class, before_paste)
        return
    subprocess.run(
        ["xdotool", "keyup", *_MODIFIERS], check=False, timeout=5
    )
    if _should_paste(text):
        # Paste and return UNCONDITIONALLY: the clipboard already holds the
        # exact text, so paste is the guarantee. Never fall back to typing
        # here — typing long/accented text on a mismatched layout both
        # corrupts it and triggers the keymap-remap freeze. The old fallback
        # bit hard: on a saturated X server the `xdotool key ctrl+v` call
        # pasted fine but timed out *waiting to return*, so we wrongly
        # concluded failure and re-typed all 1127 chars on top (paste-then-
        # type-during-freeze). Best-effort paste, clipboard is the net.
        _paste_into_focus(focus_class)
        return
    # delay 10: at 2 ms, ibus/app input queues drop and reorder chars under
    # load ("l'application et" landed as "l'applicat ionet" while the history
    # DB held the correct text). The old "frozen keyboard" complaint that
    # motivated delay 2 was the stuck-modifier bug above, not the delay.
    subprocess.run(
        ["xdotool", "type", "--delay", "10", "--", text],
        check=True,
        timeout=120,
    )


def _paste_into_focus(focus_class: str = "") -> None:
    """Best-effort Ctrl+V into the focused window. The clipboard already
    holds the text (deliver() set it first), so every step here is allowed
    to fail quietly — a missed paste leaves the text one manual Ctrl+V away,
    never re-typed. `focus_class` (captured at take-start) is preferred over
    a live read, which can race a window switch between stop and paste."""
    wm_class = focus_class
    if not wm_class:
        try:
            wm_class = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowclassname"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            ).stdout
        except subprocess.SubprocessError:
            wm_class = ""  # unknown focus → assume not a terminal, plain Ctrl+V
    combo = _paste_combo(_pair_is_terminal(wm_class))
    # check=False + swallow timeout: the keystroke is dispatched to the X
    # server synchronously, so whether xdotool *returns* promptly under load
    # is irrelevant to whether the paste landed. A TimeoutExpired here used
    # to bubble up and trigger a re-type — never again.
    try:
        subprocess.run(["xdotool", "key", combo], check=False, timeout=10)
    except subprocess.SubprocessError:
        pass
    print(f"paste: {combo} into '{wm_class.strip() or '?'}'")


def to_clipboard(text: str) -> None:
    # On Wayland only wl-copy reaches the clipboard ydotool pastes from; xsel
    # writes the XWayland clipboard, which GNOME doesn't sync back, so the
    # paste would deliver stale/empty text. Don't fall through to it silently
    # — warn and bail (a broken setup, since setup_wayland.sh installs it).
    if _WAYLAND:
        if shutil.which("wl-copy") is None:
            print("wl-copy absent — installe wl-clipboard, sinon le collage échoue")
            return
        subprocess.run(
            ["wl-copy"], input=text.encode(), check=True, timeout=10
        )
        return
    subprocess.run(
        ["xsel", "--clipboard", "--input"],
        input=text.encode(),
        check=True,
        timeout=10,
    )
