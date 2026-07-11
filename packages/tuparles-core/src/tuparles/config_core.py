"""Central knobs. One place to retune when the hardware or taste changes."""

SAMPLE_RATE = 16_000
CHANNELS = 1

# Audio normalization (see preprocess.py): bring quiet takes up toward full
# scale before STT. No-op on loud audio, never clips.
NORMALIZE_TARGET_PEAK = 0.95  # a hair of headroom below 1.0
NORMALIZE_MAX_GAIN = 12.0  # ~+21 dB ceiling; beyond this we'd amplify hiss
NORMALIZE_SILENCE_FLOOR = 0.005  # peak below this = silence, leave it alone

# Silence trim (see preprocess.trim_silence): lop the dead lead/tail off a take
# before decode. The payoff is the CPU rungs — qwen/whisper.cpp decode every
# silent second (a field case: a 51.2s take → 20.8s qwen decode, ~half of it a
# forgotten-mic tail), whereas the GPU's in-decode VAD already skips it. MVP
# trims lead + tail ONLY, never interior pauses: a wrong trim is worse than a
# slow decode (the house asymmetric bias — when in doubt, keep the audio).
TRIM_PAD_LEAD_MS = 200  # keep this much audio before the first detected speech;
TRIM_PAD_TAIL_MS = 400  # …and after the last. VAD onsets/offsets clip tight and
# Whisper wants a beat of room, so it doesn't shear the first/last phoneme.
TRIM_MIN_RESULT_S = 1.25  # never hand an engine less than this: a VAD misfire on
# soft speech must not starve the decode — below it, keep the original buffer.
# Raised 0.5 → 1.25 after the real-take A/B (2026-07-11): two sub-1 s takes trimmed
# to 0.76/0.99 s decoded to garbage — whisper is unreliable under ~1 s. So a raw
# take already shorter than 1.25 s is a structural no-op (kept untrimmed). When in
# doubt, keep the audio. See docs/research/2026-07-11-audio-preprocess-silence-trim.md.
TRIM_MAX_REMOVED_FRAC = 0.95  # if a trim would delete more than this share of the
# take, distrust it (soft speech read as silence) and keep the original.
TRIM_RMS_TOP_DB = 30.0  # RMS-fallback silence gate: a frame quieter than the peak
# frame by more than this (dB) is silence. librosa's top_db default is 60 (a
# studio floor); 30 is tighter, tuned for a live mic's ambient noise floor.
TRIM_RMS_FRAME_MS = 30  # RMS-fallback analysis frame (~silero's 32 ms grain)

# Waveform amplitude mapping (audio.py): mic RMS (int16, ±32768) → the bubble's
# 0..1 bar height. We subtract a light noise gate, scale to a speech-typical
# peak, then apply a perceptual gamma (<1) so even soft speech lifts into a
# visible range — the bars jumping is the user's "I hear you" confirmation.
# Tune to the mic: the first values (floor 80 / full-scale 3000) were set on a
# loud desktop mic and left a quieter laptop mic (ambient RMS ~8, normal speech
# ~80-100, loud ~140-250) flat — normal speech sat *under* the floor. Lowered to
# match: floor below normal speech, full-scale near a loud peak. (Per-mic
# sensitivity / auto-gain would generalise this; the spectrum view AGCs anyway.)
LEVEL_NOISE_FLOOR = 50.0  # RMS below this = silence: bars rest flat
LEVEL_FULL_SCALE = 300.0  # RMS that should peg the meter
LEVEL_GAMMA = 0.6  # <1 lifts quiet speech; 1.0 = linear

# Live-partials sanity filter (partials.py, #3): SUPPRESS decoder-flagged junk
# from the provisional preview — never rewrite (a wrong autocorrect is worse
# than a visible mishear). These are faster-whisper's own defaults: a segment
# Whisper itself would treat as non-speech, or a degenerate repetition loop.
# Tuned to err toward *showing* — a rough partial beats a blank bubble.
PARTIAL_NO_SPEECH_MAX = 0.6  # no_speech_prob above this AND logprob below…
PARTIAL_AVG_LOGPROB_MIN = -1.0  # …this together = silence hallucination → drop
PARTIAL_COMPRESSION_MAX = 2.4  # gzip ratio above this = repetition loop → drop

# Live partials: decode only the last N seconds (the bubble elides left,
# only the tail is visible — bounding the window bounds the latency).
PARTIAL_WINDOW_S = 20
# Below this much audio, language auto-detect is a coin flip (privet!).
PARTIAL_MIN_AUDIO_S = 1.0
PARTIAL_PERIOD_S = 1.0
