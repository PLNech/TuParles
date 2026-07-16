"""What this box can actually do — probed once at boot, not assumed (#29).

The xdotool-3.x miss taught the lesson: `getwindowclassname` was silently absent
on this box's xdotool, every window-class read returned '', and terminals got a
no-op Ctrl+V — a failure that surfaced far downstream as "nothing pasted", never
as "that subcommand doesn't exist". A tool being installed says nothing about
which *subcommands* this *version* supports.

So we probe the environment once, log a one-line report, and make the
detection/fallback CHAINS explicit — so a cross-env gap is visible immediately,
not after a failed paste. The bar is "still works on my laptop on the train":
across distros, xdotool versions and display servers, every operation degrades to
a documented fallback rather than a silent no-op.

This module OBSERVES and REPORTS; it doesn't drive delivery (which already
implements these chains). The `Chain.resolved` value is the contract: a test
pins it to what `delivery.py` actually does, so the formal description and the
real code can't drift. Pure-ish — the probes shell out, but parsing is
deterministic and headless-tested by injecting a fake runner + presence check.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from tuparles.config import IS_WAYLAND

# (returncode, stdout, stderr) — best-effort; a missing/again tool is just absent.
RunResult = tuple[int, str, str]
Runner = Callable[[list[str]], RunResult]
Presence = Callable[[str], bool]


def _run(cmd: list[str]) -> RunResult:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=3)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.SubprocessError):
        return 127, "", ""


def _present(name: str) -> bool:
    return shutil.which(name) is not None


@dataclass(frozen=True)
class Tool:
    name: str
    present: bool
    version: str = ""  # first line of --version/version, "" if unknown/absent
    note: str = ""  # extra (e.g. xdotool's available subcommands)


@dataclass(frozen=True)
class Layer:
    """One rung of a fallback chain: a way to do an operation, and whether it's
    usable in this environment."""

    name: str
    usable: bool
    detail: str = ""


@dataclass(frozen=True)
class Chain:
    """An ordered fallback chain for one operation. The first usable layer wins;
    `resolved` is that layer's name, or the documented `fallback` when none are
    usable (a fallback is never a crash — at worst a graceful reduced mode)."""

    op: str
    layers: tuple[Layer, ...]
    fallback: str
    short: str = ""  # compact label for the one-line report (op when empty)

    @property
    def resolved(self) -> str:
        for layer in self.layers:
            if layer.usable:
                return layer.name
        return self.fallback

    @property
    def degraded(self) -> bool:
        """True when the preferred (first) layer isn't the one we'll use — worth
        noting even if a later layer still works."""
        return not self.layers or not self.layers[0].usable


@dataclass(frozen=True)
class Capabilities:
    display_server: str  # "wayland" | "x11"
    tools: dict[str, Tool]
    chains: tuple[Chain, ...]

    def chain(self, op: str) -> Chain | None:
        return next((c for c in self.chains if c.op == op), None)

    @property
    def clipboard_types_probeable(self) -> bool:
        """Whether clipboard *type* detection works here — the guard #28's
        restore needs to avoid clobbering a non-text payload. Wayland reads types
        via `wl-paste --list-types`; X11 needs `xclip -t TARGETS` (xsel can't list
        them). Absent → restore safely declines rather than guess."""
        if self.display_server == "wayland":
            return self.tools["wl-paste"].present
        return self.tools["xclip"].present

    @property
    def warnings(self) -> list[str]:
        """The cross-env gaps worth shouting at boot — each a real reduced mode,
        not noise. An operation on its preferred layer is silent."""
        out: list[str] = []
        for c in self.chains:
            if c.resolved == c.fallback:
                out.append(f"{c.op}: no usable tool → {c.fallback}")
        if not self.clipboard_types_probeable:
            out.append("clipboard restore limited (no type-probe tool)")
        return out

    def report(self, verbose: bool = False) -> str:
        """A one-line capability summary for the boot log; `verbose` adds a
        per-tool breakdown (the dev surface, #8)."""
        bits = " · ".join(f"{c.short or c.op}={c.resolved}" for c in self.chains)
        warns = self.warnings
        head = (
            f"capabilities: {self.display_server} · {bits} · "
            f"gaps: {'; '.join(warns) if warns else 'none'}"
        )
        if not verbose:
            return head
        lines = [head]
        for t in self.tools.values():
            mark = "✓" if t.present else "✗"
            extra = f" {t.version}" if t.version else ""
            note = f" ({t.note})" if t.note else ""
            lines.append(f"  {mark} {t.name}{extra}{note}")
        return "\n".join(lines)


# ── probes ───────────────────────────────────────────────────────────────────

# The xdotool subcommands the chains depend on. Probed individually because a
# version can ship some and not others (getwindowclassname is the cautionary one).
_XDOTOOL_SUBCOMMANDS = ("getactivewindow", "windowactivate", "getwindowclassname")


def _xdotool_has(sub: str, run: Runner) -> bool:
    """Whether this xdotool build knows `sub`. `xdotool help <sub>` lists it when
    present and prints 'Unknown command' when not — side-effect-free (no window
    is touched), unlike running the bare subcommand."""
    _rc, out, err = run(["xdotool", "help", sub])
    return "unknown command" not in (out + err).lower()


# Tools that don't speak --version spit an error to the same stream; don't show
# "unrecognized argument --version" as if it were a version.
_VERSION_NOISE = ("unrecognized", "unknown", "usage:", "invalid", "no such")


def _version(cmd: list[str], run: Runner) -> str:
    """First non-empty line of a version probe — sanitized + capped. '' when the
    tool doesn't support the probe (an error line) or is unavailable."""
    _rc, out, err = run(cmd)
    text = (out or err).strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    if any(n in line.lower() for n in _VERSION_NOISE) or not any(
        c.isdigit() for c in line
    ):
        return ""
    return line[:40]


def _xdotool_tool(present: Presence, run: Runner) -> Tool:
    if not present("xdotool"):
        return Tool("xdotool", present=False)
    line = _version(["xdotool", "version"], run)  # "xdotool version 3.20160805.1"
    ver = line.split()[-1] if line else ""
    subs = [s for s in _XDOTOOL_SUBCOMMANDS if _xdotool_has(s, run)]
    return Tool("xdotool", present=True, version=ver, note="+".join(subs))


def _simple_tool(
    name: str, present: Presence, run: Runner, version_arg="--version"
) -> Tool:
    if not present(name):
        return Tool(name, present=False)
    return Tool(name, present=True, version=_version([name, version_arg], run))


def probe(
    run: Runner = _run,
    present: Presence = _present,
    wayland: bool | None = None,
) -> Capabilities:
    """Detect the environment's tools + resolve the fallback chains. Inject `run`
    / `present` / `wayland` to test any environment headlessly."""
    is_wayland = IS_WAYLAND if wayland is None else wayland
    server = "wayland" if is_wayland else "x11"

    tools: dict[str, Tool] = {"xdotool": _xdotool_tool(present, run)}
    for name in (
        "xprop",
        "xsel",
        "xclip",
        "wl-copy",
        "wl-paste",
        "ydotool",
        "ydotoold",
        "notify-send",
        "gdbus",
    ):
        tools[name] = _simple_tool(name, present, run)

    xdo = tools["xdotool"]
    xdo_subs = set(xdo.note.split("+")) if xdo.note else set()
    has_class = "getwindowclassname" in xdo_subs
    has_activate = "windowactivate" in xdo_subs

    # Chains are display-server-aware: only the layers that even apply to THIS
    # server are listed, native path first — so `resolved`/`degraded` describe the
    # box we're on, not a hypothetical one. The cross-env story lives in both
    # branches being visible here (and in the research note), not in mixing them.
    if is_wayland:
        class_layers = (
            Layer(
                "gnome-extension", tools["gdbus"].present, "org.tuparles FocusWindow"
            ),
            Layer("xprop", tools["xprop"].present, "XWayland fallback"),
        )
        paste_layers = (
            Layer(
                "wl-copy+ydotool",
                tools["wl-copy"].present and tools["ydotool"].present,
                "Wayland clipboard + uinput Ctrl+V",
            ),
        )
        activate_layers = (Layer("gnome-ActivateById", False, "extension — not yet"),)
    else:
        class_layers = (
            Layer(
                "xprop", tools["xprop"].present, "xprop -id <id> WM_CLASS (base X11)"
            ),
            Layer(
                "xdotool-getwindowclassname",
                xdo.present and has_class,
                "newer xdotool only",
            ),
        )
        paste_layers = (
            Layer(
                "xsel+xdotool",
                tools["xsel"].present and xdo.present,
                "X11 clipboard + key Ctrl+V",
            ),
        )
        activate_layers = (
            Layer(
                "xdotool-windowactivate",
                xdo.present and has_activate,
                "X11 origin refocus",
            ),
        )

    chains = (
        Chain(
            "window_class",
            class_layers,
            fallback="empty → assume not-a-terminal (safe default)",
            short="class",
        ),
        Chain(
            "paste",
            paste_layers,
            # No xsel/ydotool: the text stays on the clipboard for a manual paste.
            # Typing is NOT the default degrade anymore (it churned the keymap and
            # froze GNOME) — it's opt-in via TUPARLES_ALLOW_TYPE_FALLBACK=1.
            fallback="clipboard, manual paste (type only if TUPARLES_ALLOW_TYPE_FALLBACK=1)",
            short="paste",
        ),
        Chain(
            "window_activate",
            activate_layers,
            fallback="no refocus — paste where focus is",
            short="activate",
        ),
    )
    return Capabilities(server, tools, chains)
