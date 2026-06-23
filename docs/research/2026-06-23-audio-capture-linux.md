# Capturing both sides of a meeting on Linux (PipeWire) — engineering brief

*Researched 2026-06-23. Verbatim research brief.*

Stack (confirmed live): **PipeWire 1.0.5 + PulseAudio shim**, default sink `float32le 2ch 48000Hz`. The `Recorder` captures mono 16k int16 via sounddevice, accumulating chunks in RAM.

## TL;DR

- **Dual-channel, not mixed.** Capture mic and the sink's `.monitor` as **two independent streams**, store as a 2-channel WAV (L=me, R=them). Diarization becomes trivial (channel = speaker side) and it's strictly more information than a mix. Keep a downmixed mono only as transcription input, derived on the fly.
- **Stream to disk, don't buffer raw float32 in RAM.** Write 16k int16 (or FLAC) incrementally.
- **Batch transcribe on "stop"** for the note-taker; live partials optional.
- **The robustness work is 80% of the real engineering:** default-sink changes mid-meeting, 48k→16k resampling, silence skipping.

## 1. Capturing "what you hear" — the monitor source

Every PipeWire/PulseAudio sink exposes a `.monitor` source carrying exactly what's played to it:

```bash
pactl list short sources | grep '\.monitor'
pactl get-default-sink
parec -d "$(pactl get-default-sink).monitor" --rate=48000 --channels=2 --format=s16le > them.raw
pw-record --target "$(pactl get-default-sink).monitor" them.wav
```

PulseAudio exposes **`@DEFAULT_MONITOR@`** (current default sink's monitor) — useful but see hot-swap caveat in §5.

**Via sounddevice/PortAudio:** monitors appear as *input* devices (`max_input_channels > 0`). Openable with `sd.InputStream(device="…monitor")`. But PortAudio naming is flaky and doesn't track default-sink changes — for the monitor side prefer driving **`parec`/`pw-record` as a subprocess** and reading stdout. Keep sounddevice for the mic.

## 2. Mic + monitor simultaneously: mix vs dual-channel

### Recommended: keep separate (dual stream → 2-ch file)

```bash
parec -d @DEFAULT_MONITOR@ --rate=16000 --channels=1 --format=s16le > them.raw &
parec -d "$(pactl get-default-source)" --rate=16000 --channels=1 --format=s16le > me.raw &
```

Transcribe each channel independently → perfect "me vs them" labels, no diarization model needed. **Channel identity is ground-truth diarization.**

| | Mix | Keep separate (recommended) |
|---|---|---|
| Diarization | needs a diarizer | free, perfect (channel = side) |
| Storage | 1× | 2× (negligible) |
| Echo/bleed | mic picks up speaker → double audio | isolated; can even cancel |
| Sync | trivial | align start times (sub-100ms fine) |
| Whisper input | feed directly | downmix `(me+them)/2`, or transcribe both |

### The PipeWire "one device" way (sample-locked)
Create a **null sink**, **loop** both mic and real sink monitor into it, capture that null sink's monitor. On PipeWire 1.0.x prefer **`module-combine-stream`** / **`pw-loopback`** over deprecated Pulse `module-combine-sink`. More setup than worth it for a note-taker — two independent `parec` into a stereo file is the pragmatic 95% solution.

## 3. Long-recording memory and storage

**Raw float32 in RAM is the trap.** 60 minutes:

| Format | Per channel, 60 min |
|---|---|
| float32 @ 16 kHz mono | ~230 MB |
| float32 @ 48 kHz stereo | ~1.4 GB (the real footprint if you forget to downsample) |
| int16 @ 16 kHz mono | ~115 MB |
| **FLAC @ 16 kHz mono** | **~40-60 MB** |

A 90-min two-channel float32 @ 48k meeting is **~4 GB in RAM** — unacceptable for a background daemon.

**Strategy: stream to disk as 16k int16, ideally FLAC.** In the callback, resample 48k→16k and write immediately. Memory stays flat. For chunked transcription, transcribe **windows of ~30 s with 2-3 s overlap**, cutting on VAD-detected silence near boundaries. De-dup the overlap by timestamp when stitching. Disk: ~100 MB/hr both channels FLAC.

## 4. Live vs batch

For a background note-taker with explicit start/stop, **batch on stop is the right default** (Whisper accuracy best with full context; live re-decode wastes GPU + flickers). **Hybrid:** cheap live VAD/level + rolling 30s partial for reassurance, authoritative transcript in one batch pass on stop (chunked so a 90-min meeting doesn't OOM). A 60-min meeting on a 4080 with faster-whisper large-v3 batches in a few minutes.

## 5. Robustness gotchas (the real work)

1. **Default sink changes mid-meeting** (plug in headphones). `pactl subscribe` emits `change` on `server`/`sink`; re-resolve `pactl get-default-sink` and restart the monitor capture, splicing a new segment. Treat brief gaps as expected; log them.
2. **Sample-rate 48k → 16k.** Ask `parec --rate=16000` (PipeWire resamples in-graph). If capturing native 48k, `scipy.signal.resample_poly(x, 1, 3)` or `soxr`. Avoid naive decimation (aliasing).
3. **Silence / VAD.** Run **Silero VAD** (cheap, CPU) per channel to skip ASR on silence + place chunk boundaries in pauses. Doubles as turn detection.
4. **Echo / double-capture.** On speakers (not headphones) the mic re-records remote audio → "them" on both channels. Detect via cross-correlation, warn to use headphones, or WebRTC AEC. Headphones make it vanish.
5. **Process lifecycle.** `parec` subprocesses must be killed on stop/crash. Wrap in a context manager / reuse the single-instance flock discipline.

## 6. Privacy & consent surface

- **Visible, unmistakable indicator** while recording (tray state) — never a silent tap.
- **Explicit start/stop only.** No auto-start.
- **Local-only and say so** — genuine privacy advantage.
- **Retention controls.** Default keep transcript, **offer to delete raw audio** after transcription; auto-purge audio after N days unless pinned.
- **Consent reminder** on first use (two-party-consent jurisdictions exist).

## Concrete architecture for TuParles

```
start_meeting():
  sink = pactl get-default-sink
  spawn parec(-d sink.monitor, 16k mono s16le) → them stream
  spawn parec(-d default-source, 16k mono s16le) → me stream  [or reuse sounddevice mic]
  write interleaved → meeting_YYYYMMDD.flac (L=me, R=them), flushing continuously
  pactl subscribe → on sink change, restart monitor capture, log gap
  per-channel Silero VAD for level UI + chunk boundaries

stop_meeting():
  kill parec procs, finalize FLAC
  VAD-chunk each channel (~30s, 2-3s overlap, cut on silence)
  faster-whisper batch each channel → merged timestamped transcript, L="Me"/R="Them"
  emit notes; offer to delete raw audio
```

Flat RAM, free diarization, follows the audio device, respects the other end of the call.
