# On battery, act as if « Préférer le CPU » were ticked

## Why

The trigger was a workshop in a customer's office: the laptop ran on battery
all afternoon, and dictation kept waking the discrete GPU for every take. The
user's standing rule was already "no GPU on battery". The software didn't know
it, so the rule depended on someone remembering to tick « Préférer le CPU »
and to untick it once back at a desk. A setting you have to remember twice a
day is a chore.

The CPU is not free either, and the one real data point we have says so. On
that machine (62 GB RAM), the maintainer's session measured
`tuparles transcribe --device cpu` on 30 s of audio at **65 s wall and ~343 %
CPU**: about 2.2× slower than real time, with three to four cores busy the
whole time. That is the file path: CTranslate2 int8 with the `small` model.
It is **not** the daemon's CPU rung (whisper.cpp `base`, or qwen), which was
not measured here, so it bounds the batch cost, not a dictation take's. Still,
"CPU on battery" does not make work cheap. It keeps the dGPU asleep and accepts a slower
decode. GPU power draw on battery is still unmeasured. The decision rests on
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
answers True when a system battery says `Discharging`, whatever the supplies
report. The first cut also required no `Mains`/`USB` supply to be `online`,
and blind verification caught it on the dev laptop itself. It was at ~45 % and
draining, with AC `online=1` and one UCSI USB-C port `online=1` (a dock or
low-wattage PD partner), so the probe said "on AC" and kept the GPU. `online`
means a supply is connected, not that it charges. So the battery's own status
decides, and supplies are not read at all. Everything else answers False and
keeps the pre-feature behaviour: a desktop with no battery, `Charging`/`Full`/
`Not charging`, an unreadable tree, an unknown status, a box with no sysfs.
Peripheral batteries (`scope = Device`, e.g. a wireless mouse) are ignored, so
a draining mouse can't push a desktop onto CPU. The asymmetry is deliberate. A
false "on battery" silently slows a plugged-in machine. A false "on AC" just
means the old behaviour, and the user can still tick « Préférer le CPU ».

**Replug hysteresis.** Later in the same session BAT0 was seen flipping
Discharging <-> Charging on a marginal charger. Read instantly, that bounces
the engine between backends, and every return to the GPU costs a ~1.6 s CUDA
rebuild. `PowerProbe` is therefore asymmetric in time too. Unplugging is
honoured at the next read, since CPU is the safe side. Returning to mains
needs "not discharging" to hold for 30 s (`REPLUG_SETTLE_S`), and any
Discharging read restarts the window. The first reading has no history and is
trusted as-is, so a cold start on AC doesn't wait. The same goes for any read
taken more than 30 s after the previous sysfs read. Hysteresis absorbs
flapping between close reads, and a gap longer than the window carries no
flapping evidence. Reads only happen at takes, so this rule is what puts the
first take after a long idle on mains straight back on the GPU, without a
poller. (A cache hit inside the 5 s TTL is not a read and doesn't count.)

**A 5 s cache.** The probe is a directory walk with a few small reads, and it
runs twice per take: at take start (`supports_partials`) and at the final
(`transcribe`), never per partial, so an unplug mid-take keeps that take's live
previews on the GPU and moves its final decode to CPU. Caching it for 5 s makes a burst of takes cost
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
