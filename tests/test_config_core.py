import os
import subprocess
import sys
from pathlib import Path


def test_config_core_imports_without_desktop_deps():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    # Core src root ONLY (not the desktop root): the point is to prove the core
    # imports in isolation, without the desktop package's Qt/audio deps on the path.
    env["PYTHONPATH"] = str(root / "packages" / "tuparles-core" / "src")
    code = """
import sys
import tuparles.config_core

blocked = {'faster_whisper', 'sounddevice', 'PySide6'} & set(sys.modules)
assert not blocked, blocked
"""
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_pipeline_imports_without_desktop_deps():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    # Core src root ONLY (not the desktop root): the point is to prove the core
    # imports in isolation, without the desktop package's Qt/audio deps on the path.
    env["PYTHONPATH"] = str(root / "packages" / "tuparles-core" / "src")
    code = """
import sys
from tuparles.pipeline import postprocess

blocked = {'faster_whisper', 'sounddevice', 'PySide6'} & set(sys.modules)
assert not blocked, blocked
assert callable(postprocess)
"""
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
