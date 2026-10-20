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
2. `speech_db` = power mean of the frames at or above the 70th percentile of
   frame level. `noise_db` = 10th percentile of frame level.
3. No-op (input object returned, gain 0.0) when any of: fewer than 25 frames;
   `speech_db` < -70; `speech_db - noise_db` < 8 dB; `speech_db` >= -30.
4. `gain = clamp(-26 - speech_db, 0, 36)`, then limited so the post-gain sample
   peak stays at or under -1 dBFS (0.891). Under 3 dB: no-op.
5. One linear gain over the whole take. int16 in gives int16 out (rounded, and
   clipped only as a belt: the peak limit already prevents it); float keeps its
   dtype. No compression, no AGC dynamics inside a take.

| Constant | Value | Reason |
|---|---|---|
| frame | 20 ms | long enough for a stable RMS, short enough to resolve syllables |
| min frames | 25 (0.5 s) | too little audio to say where speech and floor are |
| speech percentile | 70th | a take is mostly pauses and breaths; the top ~30% of frames is speech without needing a VAD |
| floor percentile | 10th | the quietest frames are the room |
| `FAR_FIELD_SILENCE_DBFS` | -70 | below it the "speech" is digital silence or dither |
| `FAR_FIELD_MIN_SNR_DB` | 8 | no clear speech over the floor: lifting would only raise hiss, and hiss is what makes decoders hallucinate |
| `FAR_FIELD_QUIET_DBFS` | -30 | at or above, the audio is not far-field; near-field audio must stay byte-identical |
| `TARGET_SPEECH_DBFS` | -26 | a typical comfortable near-field speech level |
| `MAX_GAIN_DB` | 36 | covers the measured +29 dB with margin, but bounded so a faint take never becomes a wall of noise |
| peak ceiling | -1 dBFS | never clip, never touch the shape of a transient |
| min gain | 3 dB | a smaller lift is not worth altering the buffer |

Ordering note: a -75 dBFS signal is a no-op (below the -70 floor), a -66 dBFS
one is lifted by the full 36 dB cap, which is the "clamped, not blown up"
behaviour the tests pin.

## Setting and forensics

`far_field_gain` (default on, *Réglages › Décodage*, « Micro lointain (gain
automatique) »). Default-on is safe because the stage only acts on quiet audio
with clear structure. The applied gain is kept in
`preprocess.last_far_field_gain_db` and logged once per whole-dB change
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
- **Stacking with later conditioning.** After the lift, `speech_leveler`
  (compressor + peak makeup) or peak normalization still run. On lifted audio
  they act as before; their combined effect on far-field takes is unmeasured.
- The thresholds come from one room-mic measurement and reasoning, not a sweep.
