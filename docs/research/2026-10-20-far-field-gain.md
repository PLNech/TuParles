# Far-field gain stage (#51)

## Why

Meeting-room audio from a laptop array mic measures about -30 dBFS peak and
-48 dBFS RMS. The speech is only intelligible after roughly +29 dB. The existing
level conditioning does not reach it: peak normalization is capped
(`NORMALIZE_MAX_GAIN`) and driven by the loudest sample, and the speech
leveler compresses transients before one peak makeup. Neither is a statement
about where *speech* sits relative to the floor. This is the first of the
far-field stages of epic #56: a plain, predictable gain, set from frame levels
rather than from peaks. **It is experimental and off by default** (below).

## The algorithm

`far_field_gain(pcm, *, enabled=True) -> (pcm, gain_db)` in `preprocess.py`.
`prepare_pcm` calls it first, so every engine, the partials and the offline
file path see the same lifted audio (and whisper's in-decode VAD sees lifted
speech). Pure; median of 20 runs on one CPU core: 0.24 ms for 5 s of audio, 0.98 ms for 30 s, 4.6 ms for 120 s.

1. Cut into 20 ms frames (320 samples at 16 kHz); frame RMS in dBFS.
2. `level_db` (called `speech_db` in the code) = 90th percentile of frame dB
   (not a power mean: a mean is dominated by one loud frame, so hiss plus ONE
   click was lifted +9.5 dB and hiss plus seven soft keystrokes +25.6 dB in
   the first revision). `noise_db` = 10th percentile of frame dB.
3. No-op (input object returned, gain 0.0) when any of: fewer than 25 frames;
   level < -70; level - noise < 8 dB; fewer than 15 frames (0.3 s) at or above
   `noise_db + 8` (sustained energy, not a click); level >= -30.
   **This is a level and signal-to-noise gate. It does not classify speech
   versus non-speech**: any sustained sound that stands 8 dB over a quieter
   floor passes (see the limits).
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
| `FAR_FIELD_MIN_SPEECH_FRAMES` | 15 (0.3 s) at floor + 8 dB | the energy is sustained; a click or a few keystrokes fill only a handful of frames |
| `FAR_FIELD_SILENCE_DBFS` | -70 | below it the "speech" is digital silence or dither |
| `FAR_FIELD_MIN_SNR_DB` | 8 | no clear signal over the floor: lifting would only raise hiss, and hiss is what makes decoders hallucinate |
| `FAR_FIELD_QUIET_DBFS` | -30 | at or above, the audio is not far-field; near-field audio must stay byte-identical |
| `TARGET_SPEECH_DBFS` | -26 | a typical comfortable near-field speech level |
| `MAX_GAIN_DB` | 36 | covers the measured +29 dB with margin, but bounded so a faint take never becomes a wall of noise |
| hard limit | +-0.99 | the only place a transient is touched: a clack is clipped after the lift |
| min gain | 3 dB | a smaller lift is not worth altering the buffer |

Ordering note: a -75 dBFS signal is a no-op (below the -70 floor), a -66 dBFS
one is lifted by the full 36 dB cap, which is the "clamped, not blown up"
behaviour the tests pin.

## Setting and forensics

`far_field_gain` is **off by default** (*Réglages › Décodage*, « Micro lointain
(gain automatique) », tooltip: experimental, off until validated on real
recordings). The stage does not tell speech from other sustained sound and has
only been exercised on synthetic signals, so it is opt-in until the #53 A/B on
real room audio. Normal near-field audio comes out byte-identical either way.
The applied gain is exposed as `preprocess.last_far_field_gain_db` (for
debugging; nothing consumes it yet) and logged once per whole-dB change
(`far-field gain +N dB`): partials call `prepare_pcm` every tick and must not
flood the journal. A lift is the event worth tracing; a no-op is silent.

## What we tried: a modulation guard (reverted)

To keep non-speech from lifting we added a cheap deterministic guard: speech
modulates, so require at least 3 frame-to-frame jumps of 5 dB (counted once per
100 ms) before lifting. On our synthetic noise set it worked (a drifting fan,
a door slam and a flat burst went from +9.9..+29.7 dB to 0). A blind round with
its own speech generator then took it apart, two ways. A clack counts as one
jump, so a fan, a slam or a burst plus a clack lifts again (24 of 108
noise-plus-clack combinations lifted, +9.9 to +29.9 dB); raising the minimum to
4 only got to 15 of 108 while roughly doubling the false negatives. And it
misses short speech structurally: a single word ("oui", "non") never reaches 3
jumps (72 of 72 takes left unlifted), slow speech 30 of 72, normal speech under
a second 9 of 72, whispered speech 5 of 72. Tuning constants cannot fix a rule
whose premise (speech modulates a lot, noise does not) fails for clacks and
single words. The structural answer is a real speech detector in front of the
gain (the VAD-based gate, #54), not a cleverer envelope heuristic. We reverted
it and made the stage opt-in instead of shipping a heuristic that claims more
than it checks.

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
- **Non-stationary noise is lifted.** The stage holds back stationary hiss,
  hum and a single click (hiss plus 7, 13 or 19 soft keystrokes stay at 0), but
  anything sustained over a quieter floor passes. Measured by the blind
  verifier: a drifting pink fan at +-10 dB lifts +9.9 to +29.9 dB across -45 to
  -65 dBFS; a flat 0.5 s burst at -35 dBFS +9.3; door-slam pairs +8.5 to
  +17.8; slams at -35 dBFS +18.4; ordinary typing, 13 keystrokes in 4 s, +25.9;
  40 soft keystrokes in 4 s +16.9. Our own synthetic set agrees (fan
  +9.9/+19.8/+29.7 at -45/-55/-65 dBFS, +13.2 at -45 dBFS +-6 dB, flat burst
  +9.2, one door slam +22.0, 40 keystrokes +17.0). Mitigations: the decoder's
  own VAD filter downstream drops most non-speech, and the planned VAD-based
  speech gate (#54) is the structural answer. Until then the setting stays off
  by default.
- **Partials versus final.** Each tick of the live preview measures the
  growing buffer; the final measures the whole (trimmed) take, so the two
  gains can disagree. Measured on this revision, a 6 s quiet take (-48 dBFS, 0.4 s of lead
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
  later ticks; that case was not re-measured. Behaviour is deliberately
  unchanged: no smoothing across ticks.
- **Stacking with later conditioning.** After the lift, `speech_leveler`
  (compressor + peak makeup) or peak normalization still run. On lifted audio
  they act as before; their combined effect on far-field takes is unmeasured.
- The thresholds come from one room-mic measurement and reasoning, not a sweep.
