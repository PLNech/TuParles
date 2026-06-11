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

# Personal glossary fed to Whisper as initial_prompt (names, jargon).
VOCAB_FILE = REPO_ROOT / "vocab.txt"

# Live partials: decode only the last N seconds (the bubble elides left,
# only the tail is visible — bounding the window bounds the latency).
PARTIAL_WINDOW_S = 20
# Below this much audio, language auto-detect is a coin flip (privet!).
PARTIAL_MIN_AUDIO_S = 1.0
PARTIAL_PERIOD_S = 1.0
