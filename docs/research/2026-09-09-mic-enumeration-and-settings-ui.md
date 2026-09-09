# The mic that wasn't there, and the dialog that ate itself

Two bug reports arrived together, from one session wearing Bluetooth headphones:
the mic picker offered nothing but the built-in SoundWire mic even though
`pavucontrol` clearly listed the headset as a capture source, and *Réglages*
rendered as overlapping text in a squashed window — "this feels 1996, not 2026".

They turned out to be unrelated, and both diagnoses were more interesting than
the symptom.

## 1. PortAudio does not live on this desktop

The picker was built on `sounddevice.query_devices()`, filtered to
input-capable devices. On this machine, that returns exactly two entries:

```
0 | pulse   | ch 32 | api ALSA
1 | default | ch 32 | api ALSA
```

That is the whole list — before *and* after a `sd._terminate()/_initialize()`
rescan, which is what the dialog was already doing to catch hotplug. Meanwhile
the sound server knows about three real microphones, one of them the headset.

The reason is that PortAudio here has only the ALSA host API, and on a PipeWire
desktop the ALSA world is a *bridge*: `pulse` and `default` are plugin devices
that forward to whatever the server considers current. A Bluetooth mic is a
PipeWire node (`bluez_input.…`), never an ALSA card, so it cannot appear in an
ALSA enumeration no matter how many times you rescan. The picker was offering a
choice between two aliases for "whatever the desktop picked" — which is not a
choice, and is exactly what the user saw.

So enumeration moved to `pactl` (`pulse.py`). Three things came free:

- Bluetooth and USB mics exist at all.
- Human labels. `Bose QC Ultra 2 HP` instead of
  `alsa_input.pci-0000_00_1f.3-platform-sof_sdw.HiFi__hw_sofsoundwire_4__source`.
- Hotplug without a rescan, because pactl is queried live. The PortAudio
  snapshot-and-bounce dance is gone from the pulse path entirely.

### Routing to a source you cannot name to PortAudio

Enumerating is half the job; PortAudio still has to *open* the thing. There is
no "open the Bose" device index to pass. The lever is environment:
`PULSE_SOURCE` is honoured by libpulse (the ALSA pulse plugin passes no explicit
source, so the env wins) and `PIPEWIRE_NODE` covers pipewire-alsa, which serves
`default` and ignores `PULSE_SOURCE`. A pulse source name *is* the PipeWire node
name, so one value feeds both.

Two details that are easy to get wrong:

- **Set it around the constructor, not around `start()`.** The ALSA plugin
  connects to the server inside `sd.InputStream(...)`; by the time you call
  `start()` the source is already chosen.
- **Restore it afterwards.** The recorder's existing guarantee is that a
  headset which walks out of range mid-session degrades to the default mic
  rather than killing the take. A leaked `PULSE_SOURCE` pointing at the
  vanished headset would make the *fallback* open fail too, turning one
  failure into two. Hence `_env_overrides`, a context manager, rather than an
  assignment.

Verified end to end, not by inspection: with the Bose selected, a live
`Recorder` stream shows up in `pactl list source-outputs` attached to the
`bluez_input` source, and `PULSE_SOURCE` is unset again afterwards.

Fallback order for a stored mic name is pulse source → PortAudio name →
system default, so settings written before any of this keep resolving and no
migration was needed.

## 2. The dialog was squashing, not scrolling

*Réglages* was a single flat `QVBoxLayout` holding some thirty-five widgets,
with `setMinimumSize(380, 480)` and **no scroll area**. Its natural height ran
past a thousand pixels. A window manager will not grant that, so Qt did the
only thing left: it compressed every row below its minimum. Word-wrapped
`QLabel`s are the first casualties — a wrapped label needs a definite width to
compute its height, and when the layout gives it neither the width nor the
height it asked for, it prints one clipped line on top of its neighbour. That
is the overlapping text in the report.

The fix is structural, not cosmetic: categories in a sidebar, one
`QScrollArea(widgetResizable=True)` per page. `widgetResizable` is the load-
bearing part — it gives the inner widget a definite width, so wrapped hints
measure correctly, and it lets a tall page scroll instead of compress. The
regression guard (`tests/test_settings_layout.py`) imposes the reported
738×578 and asserts no visible widget is laid out shorter than its
`minimumSizeHint()`, on every page. Offscreen has no window manager, so the
test has to inflict the cramped size itself.

Re-homing was overdue anyway: the "Microphone" section had accumulated eight
checkboxes about decode behaviour, tray animation and the clipboard.

## 3. "Use a modern UI lib" — the toolkit was never the problem

Worth recording, because the instinct is reasonable and wrong. PySide6/Qt6 is
a 2026 toolkit; it is what VLC, OBS and Telegram Desktop ship. What looked
like 1996 was three separate things: the squish above, **zero** stylesheet
anywhere in the desktop package, and no platform theme resolved at all — this
box exports `QT_QPA_PLATFORMTHEME=qt5ct`, the *Qt5* bridge, which Qt6 ignores,
leaving bare Fusion. (See `2026-09-09-qt6-platform-theme.md`: the gtk3 plugin
is already on disk, so that half is a one-line env fix.)

Swapping toolkits would have meant rewriting the tray, the bubble and the
ribbon — all of which paint themselves — to solve a problem that was, in the
end, a missing `QScrollArea` and a missing stylesheet. We hand-rolled the QSS
(`theme.py`) instead of taking a theme dependency, for the usual reason: it
looks the same on every box including the one on the train, and it is scoped
per-window so it can never repaint the overlays.

### The QSS gotcha worth remembering: `data:` URIs load nothing

A stylesheet-painted `QCheckBox::indicator` draws no tick of its own, and Qt's
CSS-border arrow trick renders as a blob rather than a triangle. The obvious
move — inline the icons as `image: url(data:image/svg+xml;base64,…)` — fails
**silently**. Measured:

| icon source | renders? |
|---|---|
| `QImage("file.svg")` | yes |
| `QImage("data:image/svg+xml;base64,…")` | no |
| QSS `image: url(<abs path to .svg>)` | yes — 20 tick pixels |
| QSS `image: url(data:…)` | no — 0 pixels |

QSS `url()` is not a browser's: it resolves files and Qt resources, and that
is all. There is no error, no warning, no missing-image box — the arrows just
quietly disappear, which is precisely how it would have survived review. The
icons are now written to `$XDG_CACHE_HOME/tuparles/icons/`, named by
kind+colour so a palette switch writes a new file rather than serving a stale
one, and the rule is omitted entirely if the cache is unwritable.
