# Rolling committed transcript (Android) — design note

*2026-07-23. The "record-minutes-and-pray" fix.*

## The problem

While recording, a `PartialTranscriber` decoded a 15 s tail every ~5 s into a dim
italic preview that was **discarded**; the durable transcript was one post-hoc decode
of the whole WAV *after stop*. For a minutes-long note that is a single all-or-nothing
shot: a crash, a killed process, or a bad final decode loses everything you said.

## The design (user-elicited)

**Decode completed silence-bounded segments *during* recording, append them to a
growing durable transcript, and persist them as they land. What you see is what you
keep.** The tail preview stays for the unsettled last seconds only.

## Segmentation — constants and why

Pure-Kotlin `SilenceSegmenter` (unit-tested off-device) frames the live PCM stream and
cuts on silence with hysteresis. All constants live in one `SegmentationConfig`:

| Constant | Default | Why |
|---|---|---|
| `frameMs` | 30 ms | The voiced/silence decision is per fixed frame, independent of the mic's chunk size (which is ~1 s on this hardware). Frames straddling a callback are carried over. |
| `rmsThreshold` | 0.012 (normalised) | Below this a frame is silence. **Mic-dependent** (see the mic-level notes: noise floor varies per device) — this is the one constant most likely to need per-device tuning. |
| `minSilenceMs` | 700 ms | Continuous silence that closes a segment: a sentence pause, not a breath. |
| `minSegmentMs` | 3 s | A silence-close is suppressed until the open segment is this long, so a brief mid-sentence pause never fragments a segment. |
| `maxSegmentMs` | 30 s | Hard cap: a pause-free speaker is committed at this length so the durable transcript keeps growing during a monologue. |

**Contiguity by construction.** A closing segment spans `[start, now)` including its
trailing silence, and the next segment starts exactly at `now`. So segment *i*'s
`endSample` equals segment *i+1*'s `startSample` — the timeline is fully covered with no
gaps and no overlaps, which is what makes reconciliation deterministic (the transcript is
just the ordered concatenation; nothing is duplicated, nothing is lost).

## Committed-class decode, priority preserved

Segments decode through the existing `DecodeGate` **committed** path: they *wait* their
turn, never skip. The live tail preview keeps its `tryLock`-and-skip behaviour, so it
yields to segment decodes and to the final decode. The whisper context is a
process-scoped, non-thread-safe singleton; serialising every touch through the gate keeps
that invariant, and a **model switch mid-recording** just means the next segment waits for
the new context — order is preserved because segments decode one at a time in submit order.

The tail preview now snapshots only the audio *after* the last closed segment: the recorder
clears its tail ring buffer on each boundary, so settled (committed) text and unsettled
(preview) text never double-display.

## Progressive persistence + finalisation

- A note is created at **record start** (`TranscriptState.RECORDING`, hidden from the list
  until it finalises) so segments have a durable home. Segments are written to a new
  `note_segments` table (additive migration 3→4) as they decode; the note's `transcript`
  column is written *once* at finalisation (a denormalised concatenation of the segment
  rows), so FTS churn and mid-recording search hits are avoided.
- On **stop**, the WAV is written as today, then **only the remainder** (audio after the
  last committed segment) is decoded and appended, and the note is marked DONE. The whole
  WAV is never re-decoded.
- **Zero committed segments** (feature off, model arrived late, legacy rows, an instant
  stop) → the existing full-WAV post-hoc path via `TranscriptionManager`, unchanged.

## Doctrine: never silently replace committed text

A segment, once decoded and persisted, is **final**. Finalisation and recovery only
*append* the remainder; they never rewrite an earlier segment. A visible mishear beats a
silent rewrite — the same asymmetry as the command-vs-text interlocks. If a segment's
decode throws mid-recording (e.g. the model was deleted), that segment is skipped (no row,
no gap-filler) and the rest stand; the WAV survives for a desktop re-decode.

## Crash recovery — and the one honest limitation

On next launch, notes stuck in `RECORDING` are recovered: the transcript is rebuilt from
the segments already committed. **The committed text always survives a process death** —
that is the headline durability win.

The remainder (the un-committed tail) is recovered **only when the WAV reached disk**
(a crash during finalisation): the recovery decodes `wav[lastEnd:]` post-hoc and appends
it. In the common case — a crash *during* recording — the WAV does not yet exist, because
**the WAV write path is sacred and writes once, at stop** (the brief's fence: segmentation
must never risk it). So the un-committed tail audio was never persisted and cannot be
re-decoded; the committed text stands on its own, and a recording interrupted before its
first segment (no audio, no text) is marked FAILED (visible, never silently dropped).

This is a deliberate scope boundary, not an oversight: fully recovering the tail would
require streaming the WAV to disk during recording (header-at-start, patch-size-at-stop),
which reworks the one path we were told to leave untouched. See follow-ups.

## Degradation

No model → `RollingTranscriber.shouldArm()` is false → recording proceeds exactly as
before, the note goes PENDING, and the existing pending-work path decodes it when a model
lands. Feature toggle off → same. "It still works on my laptop on the train" holds: the
segmenter is pure CPU-cheap math; the decode uses whatever model is loaded (or none).

## Follow-ups

1. **Segment-context prompting.** The JNI `transcribeData` already accepts an
   `initial_prompt` (`prompt` arg). Feeding the previous segment's tail as context could
   improve boundary words. Deferred: needs a quality A/B against the code-switch eval to
   confirm it doesn't drag one segment's error into the next (conservative-by-default), and
   a cheap token budget. Note it, don't ship it blind.
2. **Crash-safe streaming WAV.** Stream PCM to the file during recording so the
   post-death *remainder* is always recoverable (not only on a finalisation crash). This is
   the single thing standing between "committed text survives" and "everything survives",
   and it is fenced off here because it reworks the WAV write path.
3. **Auto-scroll the live transcript** to the newest committed text (currently a bounded
   scrollable box, no follow).
4. **Per-device silence threshold.** `rmsThreshold` is the mic-dependent constant; a
   calibration pass (or reusing the level-meter calibration) would beat a global default.

## Device-validation checklist (native decode is device-only)

The JVM tests cover the segmenter, the rolling state machine (incl. the
no-dupes/no-loss reconciliation matrix and crash recovery), the migration, and the
ViewModel display/toggle. These need a real device (RTX-less phone, arm64):

- [ ] Segment boundaries land on real speech with the default `rmsThreshold` (tune per mic
      if segments cut mid-word or never close).
- [ ] Committed decodes keep up on a mid-range phone without starving the mic thread
      (AudioRecord underrun) during a long, dense monologue.
- [ ] The live committed text renders and grows smoothly; the italic tail sits after it and
      clears on each boundary.
- [ ] Stop finalises with only the remainder decoded (verify via logs: one committed decode
      at stop, not a full-WAV decode) and the note reads identically to a legacy full decode.
- [ ] Kill the process mid-recording (`adb shell am kill`): on relaunch the note is
      recovered with its committed segments; if the WAV is present, the remainder is
      appended.
- [ ] Model switch mid-recording (delete/activate another model): remaining segments decode
      in order with the new context, no corruption.
- [ ] Toggle off in Réglages → recording behaves exactly as the pre-rolling build.
