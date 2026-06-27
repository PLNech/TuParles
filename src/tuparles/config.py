"""Central knobs. One place to retune when the hardware or taste changes."""

import os
from pathlib import Path

from tuparles import config_core as _core

SAMPLE_RATE = _core.SAMPLE_RATE
CHANNELS = _core.CHANNELS
NORMALIZE_TARGET_PEAK = _core.NORMALIZE_TARGET_PEAK
NORMALIZE_MAX_GAIN = _core.NORMALIZE_MAX_GAIN
NORMALIZE_SILENCE_FLOOR = _core.NORMALIZE_SILENCE_FLOOR
LEVEL_NOISE_FLOOR = _core.LEVEL_NOISE_FLOOR
LEVEL_FULL_SCALE = _core.LEVEL_FULL_SCALE
LEVEL_GAMMA = _core.LEVEL_GAMMA
PARTIAL_NO_SPEECH_MAX = _core.PARTIAL_NO_SPEECH_MAX
PARTIAL_AVG_LOGPROB_MIN = _core.PARTIAL_AVG_LOGPROB_MIN
PARTIAL_COMPRESSION_MAX = _core.PARTIAL_COMPRESSION_MAX
PARTIAL_WINDOW_S = _core.PARTIAL_WINDOW_S
PARTIAL_MIN_AUDIO_S = _core.PARTIAL_MIN_AUDIO_S
PARTIAL_PERIOD_S = _core.PARTIAL_PERIOD_S

REPO_ROOT = Path(__file__).resolve().parents[2]

# Wayland needs different hotkey and delivery backends than X11 (evdev +
# ydotool/wl-copy instead of pynput + xdotool/xsel). One probe imported by
# both modules so they can never disagree and leave a half-Wayland setup.
IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"

QWEN_BINARY = REPO_ROOT / "vendor" / "qwen-asr" / "qwen_asr"
QWEN_MODEL_DIR = REPO_ROOT / "models" / "qwen3-asr-0.6b"

# Spike result: BLAS plateaus at the P-core thread count on the i9-13900H.
QWEN_THREADS = 14

# Chatter guard: ignore a SECOND combo-engage within this span of the last one.
# The edge detector (_ComboState._combo_since) already collapses a single
# physical press to one fire, so this only ever suppresses a distinct re-press —
# its sole job is mechanical switch chatter on release→re-press (sub-20 ms).
# It was 0.4 s, which silently ate legitimate rapid toggles (a quick start→stop,
# or stop→start-next): the "press again doesn't register" gap. 0.12 s clears real
# chatter while allowing ~8 toggles/s — fast enough to never feel it.
HOTKEY_DEBOUNCE_S = 0.12

# Combo held at least this long = push-to-talk: releasing stops the take.
# Shorter = a tap → toggle mode, recording continues until the next tap.
HOTKEY_HOLD_S = 0.5

# Personal glossary fed to Whisper as initial_prompt (names, jargon).
VOCAB_FILE = REPO_ROOT / "vocab.txt"
