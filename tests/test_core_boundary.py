"""The core/desktop import boundary — the load-bearing invariant of the refactor.

`tuparles-core` (the portable IP: the postprocess chain, privacy, settings, history,
commands) must be importable with NO display server, no mic, no GPU runtime present —
it is the same code that runs embedded on Android via Chaquopy. So nothing on the core
list may import a desktop-only dependency.

This gate imports every intended-core module in a fresh interpreter where the
desktop-hard deps are *blocked* at the import system. A leak (a core module that pulls
PySide6 / sounddevice / faster_whisper / pynput / evdev) fails the test with the exact
offending module, which is precisely how we keep the boundary from rotting as the
extraction (tasks/#10) proceeds.

See docs/research/2026-06-28-ui-architecture-decisions.md §2/§4 (step 3) and
docs/research/2026-06-27-portable-core-audit.md (the module classification this list
mirrors).
"""

import os
import subprocess
import sys

import pytest

# Desktop-only deps that must NEVER appear in the core import graph. (numpy is
# included: the real-time postprocess chain is stdlib-only; numpy lives in the
# optional nlp/ group, which is deliberately NOT on the core list below.)
BLOCKED = ["PySide6", "sounddevice", "faster_whisper", "pynput", "evdev", "numpy"]

# The portable IP, mirroring the extraction list in the portable-core audit §5.
# Each must import with every BLOCKED dep absent.
CORE_MODULES = [
    "tuparles.config_core",
    "tuparles.pipeline",
    "tuparles.punctuation",
    "tuparles.lexicon",
    "tuparles.repeats",
    "tuparles.syntax",
    "tuparles.syntax_features",
    "tuparles.syntax_features.caps",
    "tuparles.syntax_features.quotes",
    "tuparles.casing",
    "tuparles.spans",
    "tuparles.partials",
    "tuparles.languages",
    "tuparles.vocab",
    "tuparles.settings",
    "tuparles.privacy",
    "tuparles.privacy.core",
    "tuparles.privacy.denylist",
    "tuparles.privacy.floor",
    "tuparles.privacy.normalize",
    "tuparles.privacy.redact",
    "tuparles.privacy.secrets",
    "tuparles.privacy.structured",
    "tuparles.telemetry.sink",
    "tuparles.telemetry.record",
    "tuparles.telemetry.readout",
    "tuparles.telemetry.introspect",
    "tuparles.history",
    "tuparles.commands",
    "tuparles.quickchat",
    "tuparles.rolepacks",
    "tuparles.eval",
]

# A meta-path finder that raises ImportError for any BLOCKED root package, then the
# target module is imported. Run in a subprocess so the block can't bleed into other
# tests and the import is from a clean module cache.
_BOOTSTRAP = """
import importlib
import importlib.abc
import sys

BLOCKED = set({blocked!r})


class _Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError("BLOCKED desktop dependency in core graph: " + name)
        return None


sys.meta_path.insert(0, _Blocker())
importlib.import_module({module!r})
"""


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_module_imports_without_desktop_deps(module):
    script = _BOOTSTRAP.format(blocked=BLOCKED, module=module)
    # Inherit the parent's resolved sys.path (covers the editable poetry install).
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"{module} leaks a desktop dependency.\n{result.stderr.strip()}"
    )
