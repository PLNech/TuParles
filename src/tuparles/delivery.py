"""Deliver final text: type into the focused window, mirror to clipboard.

On X11, xdotool types short ASCII and pastes the rest. On Wayland there is
no xdotool: everything goes through the clipboard (wl-copy) and a Ctrl+V
sent by ydotool's uinput keyboard. Typing is never attempted there —
ydotool assumes a US keymap, so on an azerty layout `a` lands as `q`.

Long or multi-line text is pasted PROGRESSIVELY — several small single-line
pastes instead of one big one. Editors like Claude Code collapse a single
large/multi-line paste into a "[Pasted text]" placeholder you can't reread
before sending; collapse is judged per paste event, so small pieces stay
visible inline. Still paste-only — chunking never reintroduces typing."""

import re
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
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
    "ISO_Level3_Shift",
    "Shift_L",
    "Shift_R",
    "Super_L",
    "Super_R",
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
    # Skip the warning for a chunked delivery: its pacing is deliberate
    # (one settle + gap per piece), not a stall, so it must not cry wolf.
    if t2 - t0 > 1.0 and not _should_chunk(text):
        print(
            f"deliver slow: clipboard {t1 - t0:.1f}s, "
            f"focus-injection {t2 - t1:.1f}s ({len(text)} chars)"
        )


# Above this, char-by-char typing takes whole seconds (10 ms/char) and the
# focused app feels frozen — paste instead. Below it, typing is sub-2s and
# works everywhere, including paste-hostile fields.
PASTE_THRESHOLD_CHARS = 200

# Cap per pasted piece. Kept well under the size at which editors collapse a
# paste into "[Pasted text]" so every piece lands visible-and-rereadable. A
# paragraph longer than this is re-split at sentence ends; a runaway sentence
# is hard-cut. Tunable: too low = many pieces (slow, janty), too high = the
# editor swallows a piece into the placeholder we're trying to avoid.
MAX_CHUNK_CHARS = 200

# Between pieces: let the clipboard owner (wl-copy/xsel) actually offer the
# new content before the next Ctrl+V fires, and don't flood a busy app (an
# echo of the freeze saga — a saturated X server drops/reorders fast input).
_CHUNK_CLIP_SETTLE = 0.05
_CHUNK_PASTE_GAP = 0.12

# Printable ASCII exists on every layout in the user's switcher (us and fr
# alike). Anything beyond it can be MISSING from the active layout — é/à on
# QWERTY — and xdotool then remaps a scratch keycode per occurrence. Each
# remap broadcasts MappingNotify to every X client and gnome-shell re-grabs
# all its keybindings in response: a short accented take froze the whole
# desktop (Super/expose included) for ~30 s. Such text always goes through
# the clipboard instead — paste is layout-blind.
_KEYMAP_SAFE = set(string.printable)


def _should_paste(text: str) -> bool:
    return len(text) > PASTE_THRESHOLD_CHARS or any(c not in _KEYMAP_SAFE for c in text)


def _should_chunk(text: str) -> bool:
    # Chunk only when a single paste would collapse into "[Pasted text]":
    # over the per-piece cap, or already multi-line (the editor collapses any
    # multi-line paste regardless of length). A short single-line take pastes
    # in one shot, unchanged.
    return len(text) > MAX_CHUNK_CHARS or "\n" in text


# A sentence end (.!?… plus any trailing quote/bracket) followed by whitespace
# — the preferred place to break an over-long paragraph. The whitespace stays
# with the piece (break is *after* it) so the chunks rejoin into the exact
# original, no glued sentences.
_SENTENCE_END = re.compile(r'[.!?…]["»”\'\)\]]*\s')


def _last_break(window: str) -> int:
    """Index to cut `window` at: just after the last sentence end if any, else
    just after the last space, else the whole window (hard cut — a single
    unbroken run longer than the cap, rare in speech)."""
    best = 0
    for m in _SENTENCE_END.finditer(window):
        best = m.end()
    if best:
        return best
    space = window.rfind(" ")
    if space > 0:
        return space + 1
    return len(window)


def _split_paragraph(part: str, max_chars: int) -> list[str]:
    """One newline-free paragraph → pieces ≤ max_chars, rejoining to `part`
    exactly (separators kept). [] for an empty paragraph."""
    if not part:
        return []
    if len(part) <= max_chars:
        return [part]
    pieces = []
    rest = part
    while len(rest) > max_chars:
        cut = _last_break(rest[:max_chars])
        pieces.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        pieces.append(rest)
    return pieces


def _chunk_for_paste(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Paragraph-first split for progressive pasting. Newlines become their
    own one-char pieces (a pasted '\\n' is a literal newline, NOT Enter — it
    never submits, where typing Enter into Claude Code would). The pieces
    concatenate back to `text` byte-for-byte, and no text piece carries an
    embedded newline (so none of them trips the multi-line collapse)."""
    chunks: list[str] = []
    parts = text.split("\n")
    for i, part in enumerate(parts):
        chunks.extend(_split_paragraph(part, max_chars))
        if i < len(parts) - 1:
            chunks.append("\n")
    return chunks


# Window classes that want Ctrl+Shift+V (Ctrl+V is a control char in a tty).
# "gnome-terminal" covers the res_class form ("Gnome-terminal"); the
# -server form is the instance — Wayland reports whichever, so list both.
_TERMINALS = {
    "gnome-terminal-server",
    "gnome-terminal",
    "org.gnome.terminal",
    "kgx",
    "org.gnome.console",
    "alacritty",
    "kitty",
    "konsole",
    "xterm",
    "terminator",
    "tilix",
    "st",
    "urxvt",
    "wezterm",
    "ghostty",
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
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                _FOCUS_DEST,
                "--object-path",
                _FOCUS_PATH,
                "--method",
                f"{_FOCUS_DEST}.GetClass",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
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


# Both senders are best-effort: the clipboard already holds what should land,
# so a nonzero exit or a timeout must NOT raise — that would make deliver()
# report a correctly transcribed take as failed and skip history. A missed
# paste just leaves the text one manual paste away. Whether the tool *returns*
# promptly under load is irrelevant — the keystroke is dispatched to the
# server/uinput synchronously. OSError too: the tool could vanish between a
# which() check and here.
def _x11_paste_key(combo: str) -> None:
    try:
        subprocess.run(["xdotool", "key", combo], check=False, timeout=10)
    except (subprocess.SubprocessError, OSError):
        pass


# Two incompatible ydotool CLIs in the wild:
#  - Ubuntu's 0.1.8 is daemon-less and `key` takes a chord string ("ctrl+v").
#  - Modern ydotool (≥1.0, Arch/Fedora) talks to a ydotoold daemon and `key`
#    takes <keycode>:<state> pairs — it does NOT parse "ctrl+v". The keycodes
#    are the Linux input-event codes the daemon feeds straight to uinput.
# Presence of the `ydotoold` binary is the clean discriminator (modern ships it,
# 0.1.8 doesn't); scripts/setup_wayland.sh sets up the daemon to match.
_YDOTOOL_MODERN = shutil.which("ydotoold") is not None

# linux/input-event-codes.h — only the keys our paste chords use.
_EVDEV_CODES = {"ctrl": 29, "shift": 42, "v": 47}


def _ydotool_key_argv(combo: str) -> list[str]:
    """The `ydotool key …` argv for `combo` ("ctrl+v", "ctrl+shift+v"), in the
    syntax this host's ydotool understands."""
    if not _YDOTOOL_MODERN:
        # --delay gives 0.1.8's freshly created uinput keyboard time to be
        # recognized before the keys fire.
        return ["ydotool", "key", "--delay", "200", combo]
    codes = [_EVDEV_CODES[k] for k in combo.split("+")]
    # press in order, release in reverse — a real chord.
    seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
    return ["ydotool", "key", *seq]


def _wayland_paste_key(combo: str) -> None:
    try:
        subprocess.run(_ydotool_key_argv(combo), check=False, timeout=10)
    except (subprocess.SubprocessError, OSError):
        pass


def _paste_chunks(text: str, combo: str, send, label: str = "") -> None:
    """Paste `text` as several small pieces (see _chunk_for_paste), each set on
    the clipboard then pasted via `send` (the backend's paste-key sender),
    paced so the editor keeps every piece visible instead of folding the lot
    into "[Pasted text]". Restores the FULL text to the clipboard at the end,
    so the manual-paste backup still gives the whole take."""
    chunks = _chunk_for_paste(text)
    for chunk in chunks:
        to_clipboard(chunk)
        time.sleep(_CHUNK_CLIP_SETTLE)
        send(combo)
        time.sleep(_CHUNK_PASTE_GAP)
    to_clipboard(text)
    print(f"paste chunked: {len(chunks)} pieces, {combo} {label}".rstrip())


def _wayland_combo(focus_class: str = "") -> str:
    # Terminal vs app from the class captured at take-start when given, else a
    # live read of the GNOME focus-window extension; no class and no extension
    # falls back to Ctrl+V (the pre-extension behaviour).
    is_terminal = (
        _pair_is_terminal(focus_class) if focus_class else _focus_is_terminal()
    )
    return _paste_combo(is_terminal)


def _x11_focus_combo(focus_class: str = "") -> tuple[str, str]:
    """(wm_class, combo). `focus_class` (captured at take-start) is preferred
    over a live read, which can race a window switch between stop and paste."""
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
    return wm_class, _paste_combo(_pair_is_terminal(wm_class))


def _wayland_paste(focus_class: str = "", before_paste=None) -> None:
    """Single-shot Wayland paste. The clipboard already holds the text
    (deliver() set it first). For long/multi-line text the caller chunks
    instead — see _type_into_focus.

    Ubuntu ships ydotool 0.1.8: no ydotoold, so each call creates its own
    uinput keyboard (needs the udev rule from scripts/setup_wayland.sh).

    `before_paste`, if given, runs FIRST: the daemon hides the focus-stealing
    bubble there, so the paste lands in the user's window and not the bubble
    (Mutter ignores the bubble's no-focus hints — see capture_focus_class).
    Running it before the combo decision also lets the live fallback read the
    real target's focus, not the bubble's. Best-effort: a hide that throws
    must not abort a take whose text is already on the clipboard."""
    if shutil.which("ydotool") is None:
        print("ydotool absent — transcript au presse-papiers, colle avec Ctrl+V")
        return
    if before_paste is not None:
        try:
            before_paste()
        except Exception:
            pass
    combo = _wayland_combo(focus_class)
    _wayland_paste_key(combo)
    print(f"paste (wayland): {combo}")


def _paste_into_focus(focus_class: str = "") -> None:
    """Single-shot best-effort Ctrl+V into the focused window. The clipboard
    already holds the text (deliver() set it first). For long/multi-line text
    the caller chunks instead — see _type_into_focus.

    Never falls back to typing: typing long/accented text on a mismatched
    layout both corrupts it and triggers the keymap-remap freeze. The old
    fallback bit hard — on a saturated X server `xdotool key ctrl+v` pasted
    fine but timed out *waiting to return*, so we wrongly concluded failure
    and re-typed all 1127 chars on top (paste-then-type-during-freeze)."""
    wm_class, combo = _x11_focus_combo(focus_class)
    _x11_paste_key(combo)
    print(f"paste: {combo} into '{wm_class.strip() or '?'}'")


def _type_into_focus(text: str, focus_class: str = "", before_paste=None) -> None:
    if _WAYLAND:
        # Wayland always pastes (typing garbles azerty). Chunk the long/
        # multi-line ones so the editor doesn't fold them into "[Pasted text]".
        if _should_chunk(text):
            if shutil.which("ydotool") is None:
                print(
                    "ydotool absent — transcript au presse-papiers, colle avec Ctrl+V"
                )
                return
            if before_paste is not None:
                try:
                    before_paste()
                except Exception:
                    pass
            _paste_chunks(
                text,
                _wayland_combo(focus_class),
                _wayland_paste_key,
                label="(wayland)",
            )
        else:
            _wayland_paste(focus_class, before_paste)
        return
    subprocess.run(["xdotool", "keyup", *_MODIFIERS], check=False, timeout=5)
    if _should_paste(text):
        # Paste UNCONDITIONALLY — the clipboard holds the exact text, paste is
        # the guarantee, never re-type (see _paste_into_focus). Long/multi-line
        # text pastes progressively so it stays rereadable before you send.
        if _should_chunk(text):
            wm_class, combo = _x11_focus_combo(focus_class)
            _paste_chunks(
                text,
                combo,
                _x11_paste_key,
                label=f"into '{wm_class.strip() or '?'}'",
            )
        else:
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


# --- Voice command execution -------------------------------------------------
# Editing commands (see commands.py) act on the focused window with the SAME
# backends as paste — xdotool on X11, ydotool on Wayland — and the same
# best-effort contract (a failed keystroke is logged, never raised; the worst
# case is the user redoes it). Key NAMES (BackSpace, ctrl+z) are used on both;
# the Wayland/ydotool path mirrors the shipped paste path and still wants live
# validation on a real Wayland session (dev machine is X11).

# Universal editing keystrokes. ctrl+BackSpace deletes a word backward in
# essentially every text widget; shift+Home selects to line start so the
# follow-up BackSpace clears the line.
_DELETE_KEYS = {
    "word": "ctrl+BackSpace",
    "char": "BackSpace",
}


def _send_key(combo: str) -> None:
    (_wayland_paste_key if _WAYLAND else _x11_paste_key)(combo)


def _send_key_n(combo: str, n: int) -> None:
    for _ in range(max(1, n)):
        _send_key(combo)


def _execute_delete(cmd) -> str:
    if cmd.unit == "all":
        _send_key("ctrl+a")
        _send_key("BackSpace")
        return "tout effacé"
    if cmd.unit == "line":
        # Select to line start and delete; the extra BackSpace between lines
        # eats the joining newline so successive lines actually collapse.
        for i in range(max(1, cmd.count)):
            if i:
                _send_key("BackSpace")
            _send_key("shift+Home")
            _send_key("BackSpace")
        n = max(1, cmd.count)
        return f"{n} ligne{'s' if n > 1 else ''} effacée{'s' if n > 1 else ''}"
    combo = _DELETE_KEYS.get(cmd.unit, "ctrl+BackSpace")
    _send_key_n(combo, cmd.count)
    noun = "caractère" if cmd.unit == "char" else "mot"
    s = "s" if cmd.count > 1 else ""
    return f"{cmd.count} {noun}{s} effacé{s}"


def _open_terminal() -> str:
    for term in (
        "gnome-terminal",
        "kgx",
        "org.gnome.Console",
        "konsole",
        "alacritty",
        "kitty",
        "xterm",
    ):
        if shutil.which(term):
            try:
                subprocess.Popen(
                    [term],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return "terminal ouvert"
            except OSError:
                continue
    return "terminal indisponible"


def execute_command(cmd) -> str:
    """Run a parsed voice Command against the focused window. Returns a short
    French label for the confirmation toast. Never raises — like delivery, a
    command that misfires at the OS layer is logged, not crashed (a failed
    edit just means the user retries; a crash loses the daemon)."""
    if cmd.action == "delete":
        label = _execute_delete(cmd)
    elif cmd.action == "undo":
        _send_key("ctrl+z")
        label = "annulé"
    elif cmd.action == "open_terminal":
        label = _open_terminal()
    elif cmd.action == "help":
        label = _show_help()
    else:
        label = cmd.action
    print(f"command: {cmd.action} → {label}")
    return label


def _show_help() -> str:
    """Spoken help (#85): pop the cheat-sheet summary as a desktop notification,
    fire-and-forget (notify-send blocks if waited on). The full searchable panel
    is the tray/settings view (#83); this answers 'que peux-tu faire' on the
    spot. No notify-send → just point at the CLI in the confirmation toast."""
    from tuparles import cheatsheet

    if not shutil.which("notify-send"):
        return "aide : tuparles cheatsheet"
    body = cheatsheet.as_text(brief=True)
    try:
        subprocess.Popen(
            ["notify-send", "-a", "TuParles", "TuParles — que puis-je faire ?", body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass
    return "aide affichée"


def to_clipboard(text: str) -> None:
    # On Wayland only wl-copy reaches the clipboard ydotool pastes from; xsel
    # writes the XWayland clipboard, which GNOME doesn't sync back, so the
    # paste would deliver stale/empty text. Don't fall through to it silently
    # — warn and bail (a broken setup, since setup_wayland.sh installs it).
    if _WAYLAND:
        if shutil.which("wl-copy") is None:
            print("wl-copy absent — installe wl-clipboard, sinon le collage échoue")
            return
        subprocess.run(["wl-copy"], input=text.encode(), check=True, timeout=10)
        return
    subprocess.run(
        ["xsel", "--clipboard", "--input"],
        input=text.encode(),
        check=True,
        timeout=10,
    )
