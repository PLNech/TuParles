# CPU live partials, and the colour that broke its own promise

*2026-06-26 — a CPU-only run (GPU wedged by suspend/resume, #124) surfaced two
things worth remembering. Seeds the blog (#42).*

## The bug that wasn't a bug: green meant two things

Sprint 11 gave the bubble bars a meaning: **green = GPU, blue = CPU**. Ambient,
constant, "which silicon is decoding." Good contract. Then the *same* sprint
kept the old "landed" flash a fixed bright green — for a reason that read fine
on paper ("whiter green so landed never collides with the GPU-green ambient").

On a GPU session you never notice. On a **CPU** session the bars go
blue → blue → **green** at the moment text lands. The user's report was exact:
*"I thought blue meant CPU and green meant GPU, constant; why does it turn green
at the end?"* The colour had two meanings — *backend identity* and *success* —
and they collided precisely on the backend where it mattered.

The fix is a one-liner of principle: **signal "landed" with brightness, not
hue.** The final flash now brightens the live backend colour toward white
(`_brighten`, a lerp to white) instead of switching to a fixed green. Green
stays GPU, blue stays CPU, the hue is constant first frame to last. One colour
can carry one meaning; "more" is a second channel (lightness), not a second
colour.

Verifiability mattered here: the GPU/green path can't be exercised on a wedged
box, so `_bar_color()` was extracted from `paintEvent` to make the contract
unit-testable headless — *for every state, the hue stays the backend's.* The
green branch is now fixed-but-unseen until the GPU's back; the test is the proof
in the meantime.

## CPU partials: the verdict was about the wrong model

The standing line was "no live partials on CPU — qwen can't stream." True, *for
qwen*: a fresh process per take, ~0.4x realtime, re-decoding a growing buffer
falls behind within seconds. So the bubble showed a waveform and no preview
text. Documented reduced mode, doctrine-compliant — but a gap.

Two realisations turned "can't" into "cheap":

1. **The dep is already here.** faster-whisper is a core dependency, and its
   ctranslate2 CPU backend needs *no CUDA*. A small whisper on CPU isn't a new
   heavy dep to quarantine — it's the dep we already ship, run on the CPU. Only
   the small weights (~75–145 MB) fetch on first use, exactly like the GPU model
   already does.

2. **The loop already self-paces.** The daemon's ~1 Hz partials loop decodes a
   *bounded tail window* and subtracts elapsed time from the next wait. A slow
   decode doesn't queue up — it just yields fewer partials. So a CPU model that
   takes 0.6 s for an 8 s window (`base`, measured on this laptop) is fine; a
   long window degrades to "fewer previews," never a backlog.

So `CpuPartialsEngine` is a separate small model (`base` default, `tiny` for
low-power, a *Réglages* toggle to turn it off) that paints provisional text
while qwen's full decode lands the truth. Partials ≠ final — a different,
smaller model than the one that lands — which is the deal with *every* partial:
provisional text the final decode overwrites. If the small model can't load (no
network on first use), it degrades to waveform-only. Graceful all the way down.

The takeaway: a "can't" is often a "can't *with this component*." The reduced
mode was honest, but the gap closed the moment we asked which model, not whether
the backend could stream. Partials now degrade GPU-or-CPU like everything else.
