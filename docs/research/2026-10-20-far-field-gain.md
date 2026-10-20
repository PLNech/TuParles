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
speech). Pure, about 3 ms for 30 s on one CPU core.

1. Cut into 20 ms frames (320 samples at 16 kHz); frame RMS in dBFS.
2. `speech_db` = 90th percentile of frame dB (not a power mean: a mean is
   dominated by one loud frame, so hiss plus ONE click was lifted +9.5 dB and
   hiss plus seven soft keystrokes +25.6 dB in the first revision).
   `noise_db` = 10th percentile of frame dB.
3. No-op (input object returned, gain 0.0) when any of: fewer than 25 frames;
   `speech_db` < -70; `speech_db - noise_db` < 8 dB; fewer than 15 frames
   (0.3 s) at or above `noise_db + 8` (sustained speech, not a click);
   `speech_db` >= -30.
4. `gain = clamp(-26 - speech_db, 0, 36)`, then limited so the post-gain ROBUST
   peak (99.9th percentile of |x|, never the single max) stays at or under
   -1 dBFS (0.891). Under 3 dB: no-op.
5. One linear gain over the whole take, then the output is clipped to +-0.99.
   A push-to-talk clack exceeds that after the lift and is clipped, which is
   harmless for decoding; the speech samples are exactly the linear gain (a
   test pins it). Before, the single max set the ceiling: a 0.6 clack cut the
   lift from +18.7 to +3.5 dB and a 0.95 clack cancelled it. int16 in gives
   int16 out; float keeps its dtype. No compression, no AGC dynamics inside a
   take.

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
| peak ceiling | -1 dBFS on the p99.9 peak | one transient must not set the gain of the whole take |
| hard limit | +-0.99 | the only place a transient is touched: a clack is clipped after the lift |
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
- **Noise that looks like speech.** The p90 and the 0.3 s rule hold back
  hiss, a click and a handful of keystrokes. They do not hold back keyboard
  clatter that fills more than about 10% of the frames of a take: in the
  verifier's scenario (hiss at -60 dBFS plus 25 or more soft 20 ms keystrokes
  packed into 4 s, so about a quarter of the frames) the stage lifts +16.9 dB.
  Seven, thirteen and nineteen keystrokes in the same take stay at 0.
- **Partials versus final.** Each tick of the live preview measures the
  growing buffer; the final measures the whole (trimmed) take, so the two
  gains disagree. On the first revision the first tick was up to about 6.6 dB
  off the final gain and the spread reached 9.6 dB when the speaker got louder
  mid-take; the downstream leveler absorbs it (decoder-input RMS within about
  4 dB at the first tick, about 0.3 dB after). In the current revision the
  first 0.5 s tick is typically a no-op (under 25 frames of speech, or no
  clear speech yet) and the gain then converges to the final value within about
  1.5 s (clean take) to 3.5 s (a clack in the first second). Behaviour is deliberately unchanged: no smoothing across ticks.
- **Stacking with later conditioning.** After the lift, `speech_leveler`
  (compressor + peak makeup) or peak normalization still run. On lifted audio
  they act as before; their combined effect on far-field takes is unmeasured.
- The thresholds come from one room-mic measurement and reasoning, not a sweep.
