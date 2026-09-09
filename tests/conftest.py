"""Suite-wide isolation of user settings and cache.

`settings.get` reads `$XDG_CONFIG_HOME/tuparles/settings.json` on every call, so
without this the tests read whatever box they run on. That was survivable while
no engine consulted a setting at construction; it stopped being survivable when
the "prefer CPU" preference started reaching `ResilientEngine.__init__` — a
developer ticking a box in Réglages could turn a green suite red, which is the
worst kind of flake because it looks like a code failure.

So every test starts from the shipped defaults. A test that needs a particular
setting writes it itself; one that needs a specific config dir can still
`monkeypatch.setenv` over this.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # theme.py writes its recoloured QSS icons here; keep them out of the real one.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    yield
