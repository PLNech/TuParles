# Cross-env reliability: probe, don't assume (#29)

*2026-06-27. The build note behind the capability layer, born from the
"un sur deux" delivery hunt. Seeds the blog (#42).*

## The bug that named the doctrine

A delivery failed *one in two* takes. The cause was not the queue, not focus, not
timing. It was this: `xdotool getwindowclassname` **does not exist** on this box's
xdotool (3.20160805, from 2016). Every window-class read returned `''`, so every
*terminal* was misclassified as not-a-terminal and got a plain `Ctrl+V` — a no-op
control character in a tty. The pastes vanished.

The tool was installed. `xdotool` was on the PATH, version reported fine,
`getactivewindow` worked. **A tool being installed says nothing about which of its
subcommands this version supports.** And an unknown subcommand fails *quietly* —
empty stdout, a nonzero exit you swallow — so the failure surfaces far downstream
as "nothing pasted", never as "that command doesn't exist."

That is the cross-env trap, and it generalizes: xdotool versions, ydotool vs
ydotoold, xsel vs xclip, X11 vs Wayland, wl-clipboard present or not. Every one is
a place where *assuming* a capability silently breaks on someone else's machine —
against our bar, *"still works on my laptop on the train."*

## The fix: a probe and explicit chains

Two moves, both in `capability.py`:

**1. Probe once, at boot.** Detect what this box can actually do and log a
one-liner:

```
capabilities: x11 · class=xprop · paste=xsel+xdotool · activate=xdotool-windowactivate · gaps: clipboard restore limited (no type-probe tool)
```

The probe checks tool *presence* (xprop, xsel, xclip, wl-copy, wl-paste, ydotool,
gdbus) **and** xdotool's individual subcommands — via `xdotool help <sub>`, which
lists a known command and prints `Unknown command` for an absent one,
side-effect-free (no window is touched). That single check would have caught the
original bug at boot instead of after a hundred lost pastes. In dev mode the
report goes verbose, one line per tool.

**2. Make the fallback CHAINS explicit.** Each operation is an ordered chain of
layers, native-path first, every one ending in a *documented* fallback — never a
silent no-op:

| Operation | X11 chain | Wayland chain | Fallback |
|-----------|-----------|---------------|----------|
| window class | `xprop` → `xdotool getwindowclassname` | `gnome-extension` → `xprop` (XWayland) | empty → assume not-a-terminal |
| paste | `xsel` + `xdotool key` | `wl-copy` + `ydotool` | clipboard set, manual Ctrl+V |
| origin refocus | `xdotool windowactivate` | `gnome ActivateById` *(not yet)* | no refocus — paste where focus is |

`xprop` is the floor for window class precisely because it's *base X11* — present
across every version this can run on — where the xdotool subcommand was a moving
target. The chains are data (`Chain.resolved`/`.degraded`), so a test pins each
resolution to what `delivery.py` actually does; the description can't drift from
the code.

## The payoff loop: probe → report → bug template

The probe is not just a boot log. The same one-liner rides into every bug report
(`bugreport.environment_block()` → the prefilled GitHub issue), so a paste/focus
report arrives already carrying its environment fingerprint — we never have to ask
"which xdotool? X11 or Wayland? what's missing?". And it surfaces gaps
*proactively*: when `xclip` is absent on X11, the report says **"clipboard restore
limited (no type-probe tool)"** — explaining, before anyone hits it, why #28's
clipboard restore quietly declines on that box (it can't enumerate clipboard
types without xclip, so it won't risk clobbering a non-text payload).

## What we deliberately did *not* do

We did **not** rewrite `delivery.py` to be driven by the probe. It already
implements these chains correctly; rewiring working delivery code to consume a new
abstraction is risk without reward (*"if it ain't broke"*, and innovation tokens
are finite). `capability.py` **observes and reports**; delivery **acts**. The link
between them is a test, not a dependency. The Wayland `ActivateById` layer is
listed as a documented not-yet so the gap is visible, not silently missing.

## The travelling lesson

> Probe capabilities, don't assume them. The base-system tool with the widest
> version reach (`xprop`, `getactivewindow`) is the floor; anything newer is a
> nicety you must *check for*. And when something is missing, **say so at boot** —
> a capability you silently lack reads, downstream, as a feature that's broken.
