"""Central knobs. One place to retune when the hardware or taste changes."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Wayland needs different hotkey and delivery backends than X11 (evdev +
# ydotool/wl-copy instead of pynput + xdotool/xsel). One probe imported by
# both modules so they can never disagree and leave a half-Wayland setup.
IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"

QWEN_BINARY = REPO_ROOT / "vendor" / "qwen-asr" / "qwen_asr"
QWEN_MODEL_DIR = REPO_ROOT / "models" / "qwen3-asr-0.6b"

SAMPLE_RATE = 16_000
CHANNELS = 1

# Spike result: BLAS plateaus at the P-core thread count on the i9-13900H.
QWEN_THREADS = 14

# Tap window: both keys seen pressed within this span = trigger.
HOTKEY_DEBOUNCE_S = 0.4

# Combo held at least this long = push-to-talk: releasing stops the take.
# Shorter = a tap → toggle mode, recording continues until the next tap.
HOTKEY_HOLD_S = 0.5

# Personal glossary fed to Whisper as initial_prompt (names, jargon).
VOCAB_FILE = REPO_ROOT / "vocab.txt"

# Audio normalization (see preprocess.py): bring quiet takes up toward full
# scale before STT. No-op on loud audio, never clips.
NORMALIZE_TARGET_PEAK = 0.95  # a hair of headroom below 1.0
NORMALIZE_MAX_GAIN = 12.0  # ~+21 dB ceiling; beyond this we'd amplify hiss
NORMALIZE_SILENCE_FLOOR = 0.005  # peak below this = silence, leave it alone

# Waveform amplitude mapping (audio.py): mic RMS (int16, ±32768) → the bubble's
# 0..1 bar height. The raw RMS of speech (~300–2000) over the full int16 range
# barely moved the bars and was linear, so quiet/mid speech read as flat. We
# subtract a light noise gate, scale to a speech-typical peak, then apply a
# perceptual gamma (<1) so even soft speech lifts into a visible range — the
# bars jumping is the user's "I hear you" confirmation. Tune to the mic.
LEVEL_NOISE_FLOOR = 80.0  # RMS below this = silence: bars rest flat
LEVEL_FULL_SCALE = 3000.0  # RMS that should peg the meter
LEVEL_GAMMA = 0.6  # <1 lifts quiet speech; 1.0 = linear

# Live partials: decode only the last N seconds (the bubble elides left,
# only the tail is visible — bounding the window bounds the latency).
PARTIAL_WINDOW_S = 20
# Below this much audio, language auto-detect is a coin flip (privet!).
PARTIAL_MIN_AUDIO_S = 1.0
PARTIAL_PERIOD_S = 1.0
