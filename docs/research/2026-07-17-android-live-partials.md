# Android live partials while recording (#42)

*2026-07-17 — build note. Why, not just what.*

## The goal

Give the phone the desktop's reassurance: while you dictate, show *something* so
you know the mic is hearing you. Not a running transcript — a scoped MVP that
decodes only the **last ~15 s** of audio every few seconds and shows it,
provisional and dim, under the level meter. The durable text is still the
post-hoc decode of the whole WAV.

## Decisions that shaped the design

**Tail window, not full streaming.** Whisper is a batch decoder; there is no
cheap incremental path on-device. Re-decoding a growing buffer would get
quadratically slower on the exact long takes we care about. So we cap the window
at 15 s (~480 KB of PCM16 in a ring buffer) and accept that the preview is only
the recent tail. That is *intended*: reassurance, not a transcript.

**Self-pacing beats scheduling.** The partials loop never runs on a fixed timer
that could stack. The next window starts only after the previous decode returns:
`delay(5 s) → snapshot → decode → repeat`. A slow device makes fewer partials,
never a backlog. This is the mobile echo of the desktop's engine-lock work
(#30) — the same "committed decode outranks a speculative one" principle.

**One engine, one lock, a priority rule.** The whisper JNI context is a
process-scoped singleton and must be assumed *not* thread-safe. All native decode
now goes through a `DecodeGate` (a kotlinx `Mutex`):

- committed post-hoc decodes call `committed { }` — they **wait** their turn;
- partials call `partial { }` — a `tryLock` that **skips** (returns null) when
  the engine is busy.

So a previous note still decoding always wins; the live preview quietly yields.
Extracting this into its own tiny class made the priority behaviour unit-testable
on the JVM without the native library (`DecodeGateTest`: a suspending latch holds
the gate open, and a concurrent partial is asserted to return null).

**Structural safety, not statistics.** A partial failure is swallowed (logged),
and repeated failures stop the loop. Nothing a partial does can touch the mic,
the WAV, or the final decode — the recording path is unaffected even if the ring
buffer is never read.

**Graceful degradation, mobile edition.** `TranscriptionEngine` grew
`supportsPartials` + `transcribeSamples`, both defaulting to false/null. A build
with no model bundled reports `supportsPartials = false`, the loop is a no-op,
and recording proceeds identically. GPU-or-CPU, never GPU-or-nothing.

**Provisional reads from typography, not hue.** The preview is dim
(`onSurfaceVariant`) and italic — the same "signal state by brightness, not a
colour switch" lesson from the tray/meter work. Green still means one thing.

## Follow-ups

- No settings toggle yet (there is no settings surface in the app). "It's a
  setting" once one exists: default ON.
- A smaller/faster partials model would make the preview livelier and cheaper
  than re-running ggml-base every 5 s — folds into the model sweet-spot work (#13).
- Full running-transcript stitching (segment-append across windows, dedup at the
  seams) is the natural next step beyond this tail-window MVP.
