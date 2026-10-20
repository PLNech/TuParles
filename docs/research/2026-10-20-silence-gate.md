# Silence gate and loop guard for `transcribe` (#54)

## The report

`tuparles transcribe --device cpu` (model `small`) on a 30 s near-silent file
(peak about -30 dBFS, about 1% active frames) auto-detected Welsh and returned
one long loop of a single phrase. The expected result was an empty transcript
that says no speech was found.

## Evidence first: what reproduced, and what did not

No real recording was used. Four seeded synthetic 16 kHz mono files went
through the real `FileTranscriber` on CPU, model `small`, cached weights only
(`HF_HUB_OFFLINE=1`), default settings:

| file | peak | RMS | decoder VAD speech | output |
|---|---|---|---|---|
| pink hiss -50 dBFS RMS + 4 clicks peaking at -30 dBFS | -28.9 | -50.0 | 0.0 s | empty, `en` 0.341 |
| hum 50+100 Hz at -45 dBFS + hiss at -55 dBFS | -35.4 | -44.6 | 0.0 s | empty, `en` 0.341 |
| band-limited noise 300-3400 Hz at -60 dBFS | -46.6 | -60.0 | 0.0 s* | (not decoded) |
| hiss + clicks + one 0.35 s vowel-like burst at -30 dBFS | -28.9 | -49.8 | 0.0 s* | (not decoded) |

\* VAD-only probe, no Whisper decode (see the run budget below).

**The bug did not reproduce.** faster-whisper's own silero VAD (on by default
in the batched pipeline, with `TUNED_VAD_PARAMETERS`) found no speech in any
of them, on the raw audio and on the `prepare_pcm` output (the speech leveler
lifts the hiss to about -21 dBFS RMS). With zero audio after the VAD the
pipeline decodes nothing and returns no segments. What did reproduce is the
language symptom: detection still runs on the empty input (one dummy feature
frame) and reports `en` at 0.341, then `nn` 0.199 and **`cy` (Welsh) 0.172**.
So Welsh is one of the top answers when the model is asked about nothing.

What this implies for the field file: the batched decode only produces text
when its VAD returns at least one speech span. That file must have contained
something silero accepted (a breath, a distant voice, a knock that looks like a
syllable), and the hallucination came from decoding that one short chunk. The
synthetic vowel burst was not enough to fool silero, so the loop itself was not
reproduced here.

Run budget: the brief allowed three model runs. Run 1 (hiss + clicks) decoded
but my script crashed while saving its result (numpy floats in `json.dumps`),
run 2 repeated it, and run 3 decoded the hum file. In run 3 the band-limited
and vowel-burst files failed in my own script before reaching the decoder. The
cause was the bug described under "Side finding" below. Those two were then
checked with a VAD-only probe, which does not load Whisper.

Library facts that shaped the design (faster-whisper 1.2.1, read from source):

- `BatchedInferencePipeline.transcribe` hardcodes
  `condition_on_previous_text=False` and uses only the first temperature. It
  stores `compression_ratio_threshold` and `no_speech_threshold`, but the
  batched path never acts on either: there is no fallback and no segment skip.
  Passing them would look like a guard and do nothing, so the file path does
  not pass them.
- With `multilingual=True` (two or more selected languages) the per-chunk
  language detection inside the batched path picks the top language among all
  of them. Nothing in the API restricts it to the selection.

## Design: two structural layers, not a score

The house rule (#41, #53): safety is structural, not statistical. A "speech
probability" threshold would be one number trying to say two different
things. One is "there is nothing here", where gating is safe. The other is
"there is something here, but the decode went wrong", where gating loses a
real utterance. So there are two layers, and each has a hard, explainable rule.

### (a) Pre-decode silence gate — `preprocess.silence_gate`

A file is skipped only when **both** say nothing:

1. **Energy structure** (on the raw audio): fewer than `GATE_MIN_ACTIVE_FRAMES`
   20 ms frames at least `GATE_ACTIVE_DB` over the noise floor (the 10th
   percentile of frame dB). This is checked first, because it is cheap. Any
   structure means decode, and no detector is asked.
2. **A speech detector found no span.** On the file path the first detector
   is the decoder's own VAD (`filetranscribe._decoder_vad_span`). It is
   faster-whisper's bundled silero, run with the same parameters on the same
   `prepare_pcm` output the decoder gets. If faster-whisper is missing, the
   trim tiers answer instead: silero-vad when importable, else the RMS span.
   A detector that raises is skipped, and if none answers the file is decoded.

Because the file path asks the decoder's own VAD, **a gated file is one the
decoder would have returned empty anyway.** On this path the gate cannot lose
a transcript. What it adds is explicitness: « Aucune parole détectée », a
`no_speech` verdict with its levels in the sidecar, `language: null` instead
of the `en`/`cy` guess, and no model load. The energy clause makes the gate
stricter than the VAD alone, never looser. A decode that still returns nothing
(the VAD found nothing but the energy clause kept the file) is reported too:
`no_speech: {"reason": "decoder_empty"}`.

The RMS tier needs a word of caution. `_rms_speech_span` measures relative to
the loudest frame, so one click makes it report "speech" across the whole
file (measured: hiss + 4 clicks gives the span 0.0-30.0 s). In that tier the
gate only closes on near-digital silence. That is conservative, and it is the
intended result.

Constants (every one chosen toward "decode"):

| constant | value | why |
|---|---|---|
| `GATE_FRAME` | 20 ms | the far-field stage's grain; short enough to see a syllable |
| `GATE_MIN_FRAMES` | 25 (0.5 s) | under this there is too little to judge, so decode |
| `GATE_FLOOR_PCTL` | 10 | noise floor, same as the far-field stage |
| `GATE_LEVEL_PCTL` | 90 | reported for forensics only, decides nothing |
| `GATE_ACTIVE_DB` | 6 dB | lower than far-field's 8 dB on purpose: a faint word must count |
| `GATE_MIN_ACTIVE_FRAMES` | 8 (160 ms) | see the margins below |
| `_DECODER_VAD_MAX_SPEECH_S` | 30 | the batched pipeline replaces the VAD's max speech duration with the model chunk length (30 s) |

Measured active time (frames 6 dB over the floor) on the test signals
(`tests/test_silence_gate.py`, seeded, pink hiss high-passed at 20 Hz), plus
one extra 0.3 s burst measured with the same generators:

| signal | active | verdict (detector says "none") |
|---|---|---|
| hiss -50 dBFS, hum, band-limited -60 dBFS, digital zero, hiss + 4 clicks | 0.00 s | gated |
| hiss + 40 clicks over 30 s | 0.08 s | gated |
| one 0.3 s word-like burst, 6 dB over the hiss | 0.24 s | decode |
| one 0.6 s word-like burst, 6 dB over the hiss | 0.24 s | decode |
| one 0.6 s word-like burst, 10 dB over the hiss | 0.28 s | decode |
| 3 s faint phrase, 6 dB over | 1.22 s | decode |
| 10 s quiet bursts, 8 dB over | 4.30 s | decode |
| near-field speech-like, 30 dB over | 15.82 s | decode |

The threshold sits between 0.08 s (the worst noise) and 0.24 s (the faintest
word), at 0.16 s, so there is a factor of 1.5 on either side. Unfiltered pink
noise, whose energy reaches below 1 Hz (the repro file above), drifts slowly
in level and measures 2.8 s "active": it is decoded, not gated. The cost of
that miss is a wasted decode, never a lost word.

### (b) Post-decode loop guard — `repeats.find_loop` / `cut_loops`

`filetranscribe.guard_repetition` runs the decode as one word stream across
segments, because Whisper often splits a loop into many one-phrase segments.
A **loop** is a phrase of up to `LOOP_MAX_PHRASE_WORDS` (16) words, compared
without case or punctuation, that repeats verbatim at least `LOOP_MIN_COPIES`
(4) times in a row and covers at least `LOOP_MIN_WORDS` (12) words. So a
one-word loop needs 12 copies, two words need 6, and three or more need 4.
The guard keeps one copy, drops the other copies and any partial copy right
after them, and keeps whatever follows. On a real hallucination the loop runs
to the end of the window, so nothing follows it. If the rule fires on real
speech, keeping the tail loses less than truncating it. The brief said
"truncate at the first repetition". This is that cut, minus deleting what
comes after.

Why those numbers: real speech repeats a sentence twice for emphasis, and
sometimes a word or a short chant three times ("non non non", "on y va" x3).
Verbatim four times over 12 words is very rare in a meeting. It is still
more conservative than the daemon's sentence rule (`collapse_repeats`,
3 identical sentences), because a transcript is a record. The cut is never
silent: the block ends with ` […]` in the txt, and the JSON has
`repetition: {phrase, copies}` per message and `truncated_repetition` at the
top. `repetition_guard: false` keeps the raw decode. The gzip
`compression_ratio` was not used as a trigger, because it says "repetitive"
without saying where to cut. It is still in each message's annotations.

### (c) Language

Already handled where it can be. One selected language is forced
(`decode_language_opts`). With none selected there is no list to restrict
to. With two or more, the batched multilingual path detects the language per
chunk among all languages, and the API cannot restrict that. Changing it
would mean re-implementing the batched decode or adding a new language
policy, which is out of scope. What changed: a gated file reports
`language: null` instead of a guess from empty audio, and the sidecar now
carries `language_probability`, so a 0.34 detection is visible as such.

## The daemon

Left alone. Its final decode already goes through `pipeline.postprocess`,
which runs `collapse_repeats` (3+ identical sentences). Adding the word-level
cut there would change dictation behaviour, and it is not a clean one-line
reuse. Its decodes also run VAD-filtered on trimmed takes.

**Side finding, not fixed here:** `GpuEngine.transcribe` (the final, batched)
passes the shared `TUNED_VAD_PARAMETERS` dict, and faster-whisper pops
`max_speech_duration_s` off it. After the first GPU final, the GPU partials
(`WhisperModel.transcribe`, sequential, same dict) run with faster-whisper's
default (no maximum) instead of 30 s. The file path now passes a copy, and a
test guards it. The daemon needs the same one-word fix, plus a test, as its
own change.

## Not validated

- **No real-audio eval.** Every gate threshold comes from synthetic signals.
  The field file was not available, and the bug itself did not reproduce.
- The loop guard was tested on constructed text, not on a captured Whisper
  hallucination.
- The silero-vad package tier was not exercised (it is not installed here).
  The tests inject detectors. The decoder-VAD tier was exercised locally (real
  faster-whisper, CPU), and its test skips in CI, where faster-whisper is
  absent.
- Next: re-run the field file. Its stderr line (`porte de silence : …`, or the
  `boucle de répétition coupée` line) and the sidecar will show which layer
  fired.
