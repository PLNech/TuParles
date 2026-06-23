"""Central knobs. One place to retune when the hardware or taste changes."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

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

# Live partials: decode only the last N seconds (the bubble elides left,
# only the tail is visible — bounding the window bounds the latency).
PARTIAL_WINDOW_S = 20
# Below this much audio, language auto-detect is a coin flip (privet!).
PARTIAL_MIN_AUDIO_S = 1.0
PARTIAL_PERIOD_S = 1.0
