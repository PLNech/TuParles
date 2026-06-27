# Cross-environment compatibility & troubleshooting

TuParles runs on your own silicon, across distros, display servers (X11 and
Wayland) and tool versions. This page is the detailed map: what each feature
needs, how to read your machine's capability report, and how to fix the common
gaps. The README stays lean; the detail lives here.

> **The doctrine** (`docs/research/2026-06-27-cross-env-capability-layers.md`):
> *probe capabilities, don't assume them.* A tool being installed says nothing
> about which of its *subcommands* your version supports — so TuParles probes
> what your box can actually do at boot, picks the best available layer for each
> operation, and degrades to a documented fallback (never a silent no-op) when a
> tool is missing.

## Read your capability report

Every launch logs one line (look in the journal: `journalctl --user -t tuparles`
or wherever your launcher sends stdout):

```
capabilities: x11 · class=xprop · paste=xsel+xdotool · activate=xdotool-windowactivate · gaps: none
```

Or print it any time:

```bash
tuparles diag        # full per-tool breakdown + environment block
```

- **`class=`** how the focused window's class is read (drives terminal detection
  → which paste shortcut is used).
- **`paste=`** how text is delivered.
- **`activate=`** whether a queued take can refocus its origin window (#14).
- **`gaps:`** anything running on a fallback instead of the preferred layer —
  these are the lines worth acting on.

## What each feature needs

| Operation | X11 (preferred → fallback) | Wayland (preferred → fallback) | If nothing available |
|-----------|----------------------------|--------------------------------|----------------------|
| **Window class** (terminal detection) | `xprop` → newer `xdotool getwindowclassname` | GNOME focus-window extension → `xprop` (XWayland) | empty → treated as not-a-terminal (safe default) |
| **Paste** (delivery) | `xsel` + `xdotool key` | `wl-copy` + `ydotool` | clipboard is set; paste manually with Ctrl+V |
| **Origin-window refocus** (queued takes) | `xdotool windowactivate` | GNOME `ActivateById` *(not yet implemented)* | take pastes wherever focus is now |
| **Clipboard restore** (#28, opt-in) | `xclip` (to read clipboard *types*) | `wl-paste` | restore safely declines (won't risk clobbering a non-text payload) |
| **Live partials on CPU** | faster-whisper CPU model | same | waveform only, no streaming text |

`xprop` is the floor for window class because it's *base X11* — present across
every version. The newer `xdotool getwindowclassname` is a nicety we use only when
it actually exists (it was absent on xdotool 3.x, the bug that started all this).

## Required tools by setup

**X11 (the default path):**

```bash
sudo apt install xdotool xsel xclip xprop     # xprop ships in x11-utils
```

- `xdotool` — paste keystroke, active window, origin refocus.
- `xsel` — clipboard write (the delivery backup + paste source).
- `xclip` — *only* needed for clipboard **restore** (#28); it can enumerate
  clipboard types, which `xsel` can't. Skip it if you don't use that opt-in.
- `xprop` — window class, the version-proof way.

**Wayland (GNOME):**

```bash
bash scripts/setup_wayland.sh     # input group · uinput rule · wl-clipboard + ydotool
```

- `wl-clipboard` (`wl-copy`/`wl-paste`) — clipboard + type probe.
- `ydotool` (+ `ydotoold` running) — the paste keystroke via uinput.
- The bubble renders via XWayland (`QT_QPA_PLATFORM=xcb`) so placement and
  stickiness work; delivery still uses the Wayland tools.

## Troubleshooting by symptom

**"Nothing pastes into my terminal" (text vanishes in kitty/Claude Code).**
Your `xdotool` likely lacks `getwindowclassname` *and* `xprop` is missing, so the
terminal isn't detected and gets a plain Ctrl+V (a no-op in a tty). Install
`xprop` (`x11-utils`). Check `tuparles diag` shows `class=xprop`.

**"The whole desktop freezes for ~30s on an accented take."**
Non-ASCII typed on a US layout makes `xdotool` remap keycodes, storming every X
client. TuParles routes such text through the clipboard to avoid this — if you
still see it, make sure you're on a current build and that `xsel`/`wl-copy` is
present (so paste, not typing, is used).

**"A queued take pasted into the wrong window."**
Origin-window refocus is X11-only (`xdotool windowactivate`). On Wayland it's not
yet possible (no `ActivateById`), so `activate=` shows the fallback and takes
paste where focus is. On X11, check `xdotool` is present.

**"Clipboard restore isn't preserving my clipboard."**
On X11 it needs `xclip` to read clipboard *types* safely; without it the feature
declines rather than risk destroying a non-text payload (an image/files). The
`gaps:` line says so. Install `xclip`, or leave the (default-off) setting off.

**"Green bars turned blue."**
The GPU dropped to CPU mid-session (often a suspend/resume CUDA death). Expected
and self-healing — a one-time toast says "Passé sur CPU". Reload `nvidia_uvm` to
recover the GPU, or restart the daemon.

## Reporting a cross-env bug

Two ways, both self-documenting:

1. **`tuparles report "short summary"`** — opens a GitHub issue in your browser,
   pre-filled with your environment + capability line.
2. **`tuparles diag`** — prints the same block; paste it into a [new issue]
   (the bug-report form asks for it).

The capability line is the single most useful thing you can include — it tells us
your display server, tool versions, and exactly which layer each operation
resolved to, so we never have to play twenty questions.

[new issue]: https://github.com/PLNech/TuParles/issues/new/choose
