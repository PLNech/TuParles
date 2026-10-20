# Far-field gain stage (#51)

## Why

Meeting-room audio from a laptop array mic measures about -30 dBFS peak and
-48 dBFS RMS. The speech is only intelligible after roughly +29 dB. The existing
level conditioning does not reach it: peak normalization is capped
(`NORMALIZE_MAX_GAIN`) and driven by the loudest sample, and the speech
leveler compresses transients before one peak makeup. Neither is a statement
about where *speech* sits relative to the floor. This is the first of the
far-field stages of epic #56: a plain, predictable gain, measured on speech
frames rather than on peaks.

## The algorithm

`far_field_gain(pcm, *, enabled=True) -> (pcm, gain_db)` in `preprocess.py`.
`prepare_pcm` calls it first, so every engine, the partials and the offline
file path see the same lifted audio (and whisper's in-decode VAD sees lifted
speech). Pure; median of 20 runs on one CPU core: 0.3 ms for 5 s of audio, 1.2 ms for 30 s, 5.3 ms for 120 s.

1. Cut into 20 ms frames (320 samples at 16 kHz); frame RMS in dBFS.
2. `speech_db` = 90th percentile of frame dB (not a power mean: a mean is
   dominated by one loud frame, so hiss plus ONE click was lifted +9.5 dB and
   hiss plus seven soft keystrokes +25.6 dB in the first revision).
   `noise_db` = 10th percentile of frame dB.
3. No-op (input object returned, gain 0.0) when any of: fewer than 25 frames;
   `speech_db` < -70; `speech_db - noise_db` < 8 dB; fewer than 15 frames
   (0.3 s) at or above `noise_db + 8` (sustained energy, not a click);
   fewer than 3 modulation events (below); `speech_db` >= -30.
   A modulation event is a frame-to-frame change of at least 5 dB with one
   side at or above `noise_db + 8`, counted at most once per 100 ms. Speech
   jumps by several dB all the time; a fan with a slow level drift never does,
   a door slam has one (its onset), a flat burst two (on, off).
4. `gain = clamp(-26 - speech_db, 0, 36)`. Under 3 dB: no-op. There is NO
   peak-based reduction: at the -26 dBFS target speech peaks sit at about
   -14 to -8 dBFS, far under the limit below, so a ceiling is redundant for
   speech, and every peak rule tried let a transient veto the lift. The first
   revision's single-max ceiling cut a 0.6 clack's lift from +18.7 to +3.5 dB
   and a 0.95 clack cancelled it; the p99.9 ceiling only ignored a transient
   with fewer than about 0.1% loud samples (a 20 ms clack on a 4 s take lost
   11.9 dB, three 20 ms clacks cancelled the lift, a single 8 ms clack on a
   1.5 s take lost 12.5 dB), and cost 68-84% of the runtime.
5. One linear gain over the whole take, then the output is clipped to +-0.99.
   A push-to-talk clack exceeds that after the lift and is clipped, which is
   harmless for decoding. A grid test (take 1.5/3/6 s, 1-3 clacks, 8/20 ms,
   amplitude 0.6/0.95: 36 cells) pins that every cell lifts within 3 dB of the
   same take without clacks, that the output never exceeds 0.99, and that the
   non-clack samples equal speech times the gain exactly. int16 in gives int16
   out; float keeps its dtype. No compression, no AGC dynamics inside a take.

| Constant | Value | Reason |
|---|---|---|
| frame | 20 ms | long enough for a stable RMS, short enough to resolve syllables |
| min frames | 25 (0.5 s) | too little audio to say where speech and floor are |
| speech percentile | 90th, in dB | a take is mostly pauses and breaths; the 90th percentile sits in the speech frames without needing a VAD, and a dB percentile cannot be dragged up by one click |
| floor percentile | 10th | the quietest frames are the room |
| `FAR_FIELD_MIN_SPEECH_FRAMES` | 15 (0.3 s) at floor + 8 dB | speech is sustained; a click or a few keystrokes fill only a handful of frames |
| `FAR_FIELD_SILENCE_DBFS` | -70 | below it the "speech" is digital silence or dither |
| `FAR_FIELD_MIN_SNR_DB` | 8 | no clear speech over the floor: lifting would only raise hiss, and hiss is what makes decoders hallucinate |
| `FAR_FIELD_QUIET_DBFS` | -30 | at or above, the audio is not far-field; near-field audio must stay byte-identical |
| `TARGET_SPEECH_DBFS` | -26 | a typical comfortable near-field speech level |
| `MAX_GAIN_DB` | 36 | covers the measured +29 dB with margin, but bounded so a faint take never becomes a wall of noise |
| hard limit | +-0.99 | the only place a transient is touched: a clack is clipped after the lift |
| modulation event | 5 dB jump, 100 ms apart, at least 3 | chosen from the synthetic speech-like signals (the weakest, a 1.5 s take with 0.4 s bursts, has 4 events at 5 dB; a flat burst has 2, a door slam 1, a drifting fan 0); the margin is one event each way, which is thin |
| min gain | 3 dB | a smaller lift is not worth altering the buffer |

Ordering note: a -75 dBFS signal is a no-op (below the -70 floor), a -66 dBFS
one is lifted by the full 36 dB cap, which is the "clamped, not blown up"
behaviour the tests pin.

## Setting and forensics

`far_field_gain` (default on, *Réglages › Décodage*, « Micro lointain (gain
automatique) »). Default-on is safe because the stage only acts on quiet audio
with clear structure. The applied gain is exposed as
`preprocess.last_far_field_gain_db` (for debugging; nothing consumes it yet)
and logged once per whole-dB change
(`far-field gain +N dB`): partials call `prepare_pcm` every tick and must not
flood the journal. A lift is the event worth tracing; a no-op is silent.

## What is NOT validated

- **No WER or recall eval on real far-field audio yet.** The tests use seeded
  synthetic signals only (AM-modulated 100-3000 Hz noise bursts over a quieter
  floor) and prove the contract (levels, ceilings, no-ops, dtypes), not that
  decoding improves. The eval lane is #53.
- **It also amplifies the room noise.** A single linear gain lifts speech and
  floor together; the 8 dB SNR gate only refuses the clear cases. A room where
  speech sits barely over a loud floor is the failure mode to look for.
- **Interplay with the tuned VAD and the silence trim.** The trim
  (`trim_silence`) runs at capture handoff in the daemon, *before*
  `prepare_pcm`. Resolved: it now runs its speech detection (silero tier and
  RMS fallback alike) on a far-field-lifted float copy, computed once up front,
  while still slicing and returning the original unlifted buffer (dtype
  preserved); the `prepare_pcm` lift then applies to the trimmed slice. Trim and
  decode therefore decide on the same speech, and a faint take is no longer
  judged "silent" by the RMS tier's absolute floor (peak under 0.005, about
  -46 dBFS). The RMS tier's 30 dB gate is relative to the loudest frame, so
  its span was already scale-invariant above that floor; the lift's real effect
  there is the floor, and on silero (not importable in the dev venv, so this
  tier is untested here) its absolute speech-probability behaviour on a
  -48 dBFS take. The engines' in-decode VAD runs after `prepare_pcm` and always
  saw lifted speech. Silero on real far-field audio remains a #53 measurement.
- **Noise that looks like speech.** The p90, the 0.3 s rule and the modulation
  rule hold back hiss, a click, a handful of keystrokes (7, 13 and 19 soft
  20 ms keystrokes in 4 s stay at 0), a drifting fan (-45/-55/-65 dBFS at +-10
  dB, and -45 at +-6 dB: all 0, formerly +9.9/+19.8/+29.7 and +13.2), a door
  slam (formerly +22.0) and a flat burst (formerly +9.2). Measured limits that
  remain:
  - **Dense typing** reads as speech: 40 soft keystrokes packed into 4 s
    (hiss at -60 dBFS) lift +17.0 dB, and 25 or more packed ones +16.9 dB.
    Keystrokes jump 20 dB per click, so a modulation rule cannot tell them
    from syllables; telling them apart needs a spectral or crest-factor cue.
  - **A few slams or bursts** (three or more events 100 ms apart) pass the
    modulation rule and lift.
  - The 3-event minimum is tuned on synthetic speech only (see the constants
    table); a mumbled, flat-delivery take could fall under it.
- **Partials versus final.** Each tick of the live preview measures the
  growing buffer; the final measures the whole (trimmed) take, so the two
  gains can disagree. Measured on a 6 s quiet take (-48 dBFS, 0.4 s of lead
  floor), gain per 0.5 s tick, clean: 0.0 (0.5 s, only 0.1 s of speech so far),
  then 18.8, 18.8, 18.6, 18.5, 18.5, 18.6, 18.5, 18.5, 18.5, 18.4, 18.5 against
  a final 18.5 dB: at most 0.3 dB apart from the second tick, 0.1 dB after 3 s.
  With a 0.95 clack in the first 20 ms: 0.0, then 18.5, 18.6, 18.6, 18.5, 18.4,
  18.5 ... against a final 18.4: 0.2 dB from the second tick, 0.1 dB after 3 s.
  The first tick is the exception: it is a no-op until 0.3 s of speech
  exists, so the first 0.5 s partial decodes unlifted and the final decodes
  lifted by about 18 dB; the downstream leveler absorbs that (peak
  normalization or the compressor re-levels the buffer anyway). An earlier
  revision (power-mean level, single-max ceiling) disagreed by up to about
  6.6 dB at the first tick and 9.6 dB when the speaker got louder mid-take.
  A speaker who gets much louder mid-take moves the p90 and so the gain of the
  later ticks; that case was not re-measured on this revision. Behaviour is
  deliberately unchanged: no smoothing across ticks.
- **Stacking with later conditioning.** After the lift, `speech_leveler`
  (compressor + peak makeup) or peak normalization still run. On lifted audio
  they act as before; their combined effect on far-field takes is unmeasured.
- The thresholds come from one room-mic measurement and reasoning, not a sweep.
