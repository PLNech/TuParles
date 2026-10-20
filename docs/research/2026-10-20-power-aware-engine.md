# On battery, act as if « Préférer le CPU » were ticked

## Why

The trigger was a workshop in a customer's office: the laptop ran on battery
all afternoon, and dictation kept waking the discrete GPU for every take. The
user's standing rule was already "no GPU on battery". The software didn't know
it, so the rule depended on someone remembering to tick « Préférer le CPU »
and to untick it once back at a desk. A setting you have to remember twice a
day is a chore.

The CPU is not free either, and the one real data point we have says so. On
that machine (62 GB RAM), `tuparles transcribe --device cpu` on 30 s of audio
with the `small` model took **65 s wall at ~343 % CPU**: about 2.2× slower than
real time, with three to four cores busy the whole time. So "CPU on battery"
does not make a take cheap. It keeps the dGPU asleep and accepts a slower
decode. We have not measured the GPU's draw on battery. The decision rests on
the owner's rule plus that CPU figure, not on a watt comparison. A proper A/B
would need a wall-power meter or `upower` discharge-rate logging. That's a
follow-up, not a precondition.

## Design

**Reuse the seam, don't add a mode.** `ResilientEngine` already had everything
needed for « Préférer le CPU » (#137): a lazily-built GPU, `_on_cpu` plus a
*reason*, and `_sync_cpu_preference()` called at take start
(`supports_partials`) and on each final (`transcribe`). The battery case is the
same preference with a different source:

```python
def cpu_preference() -> str | None:
    if settings.get("prefer_cpu"):
        return "prefer_cpu"
    if settings.get("battery_aware") and power.on_battery():
        return "battery"
    return None
```

The engine only cares whether a preference is present. The source is kept
separately (`_preference_source`) for the log line and the toast. Because the
state is the same, the blue tray/bubble colour, telemetry's `engine_name`,
CPU partials and the "never construct CUDA" guarantee all come for free.
`tuparles transcribe --device auto` reads the same function.

**Reversible preference, irreversible failure.** `_on_cpu_reason` stays two
values: `"preference"` (from the checkbox *or* the battery) and `"failure"`
(the card died and a rebuild failed). A preference lifting rebuilds the GPU
lazily, at the next take after the plug goes in. A failure is never revived by
a preference flip: plugging in is no evidence that a dead CUDA context came
back, and retrying it would cost ~1.6 s per take. A rebuild that fails on
return to mains becomes a failure and stops retrying. That's the same rule the
checkbox already followed.

**Fail toward the GPU only without battery evidence.** `power.read_on_battery`
answers True only when a system battery says `Discharging` *and* no
`Mains`/`USB` supply is `online`. Everything else answers False and keeps the
pre-feature behaviour: a desktop with no battery, `Charging`/`Full`/
`Not charging`, an unreadable tree, an unknown status, a box with no sysfs.
Peripheral batteries (`scope = Device`, e.g. a wireless mouse) are ignored, so
a draining mouse can't push a desktop onto CPU. The asymmetry is deliberate. A
false "on battery" silently slows a plugged-in machine. A false "on AC" just
means the old behaviour, and the user can still tick « Préférer le CPU ».

**A 5 s cache.** The probe is a directory walk with a few small reads, and it
runs once or twice per take. Caching it for 5 s makes a burst of takes cost
one walk, and an unplug is still seen by the next take that starts more than
5 s later. No UPower, no D-Bus, no new dependency.

**It's a setting.** `battery_aware` defaults to on, with a Réglages toggle
right below « Préférer le CPU »: « Économiser la batterie (CPU sur batterie) ».
`prefer_cpu` still wins on mains. The one-time GPU→CPU toast says
« Sur batterie — passé sur CPU pour l'économiser » instead of sounding like a
breakdown.

## Known limit

The engine can drop the model, but it can't drop the CUDA context once one
exists (~190 MB, measured for #137). After a mid-session unplug, decodes stay
off the card, but that leftover context may keep the dGPU from fully sleeping
(runtime power management). A daemon *started* on battery never touches CUDA
at all. Measuring how much this costs is the same follow-up as above.
