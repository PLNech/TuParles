"""Telemetry primitives: events persist locally, the opt-out is a hard gate,
and the readout answers the discovery question."""

import pytest

from tuparles import syntax, telemetry
from tuparles.pipeline import postprocess
from tuparles.syntax import SyntaxFeature, apply_syntax
from tuparles.telemetry import readout, sink


def _isolate(tmp_path, monkeypatch):
    # sink lives in XDG_DATA_HOME (beside history.db); the gate in XDG_CONFIG_HOME.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


class TestPrimitives:
    def test_event_persists(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.event("command.fired", name="undo")
        rows = sink.read()
        assert len(rows) == 1
        _ts, name, attrs = rows[0]
        assert name == "command.fired"
        assert attrs == {"name": "undo"}

    def test_lands_in_history_db(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.event("entry.dictation", source="hotkey")
        # one store, shared with utterances — the dashboard reads both from here
        assert (tmp_path / "data" / "tuparles" / "history.db").exists()

    def test_timer_records_elapsed(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        with telemetry.timer("decode.span", engine="cpu"):
            pass
        _ts, name, attrs = sink.read()[0]
        assert name == "decode.span"
        assert attrs["engine"] == "cpu"
        assert "elapsed_s" in attrs and attrs["elapsed_s"] >= 0


class TestOptOut:
    def test_disabled_is_a_no_op(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.set_enabled(False)
        assert telemetry.enabled() is False
        telemetry.event("command.fired", name="undo")
        with telemetry.timer("decode.span"):
            pass
        assert sink.read() == []

    def test_re_enable_resumes(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.set_enabled(False)
        telemetry.event("command.fired")
        telemetry.set_enabled(True)
        telemetry.event("command.fired")
        assert len(sink.read()) == 1

    def test_default_on(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert telemetry.enabled() is True


class TestReadout:
    def test_usage_counts_and_prefix(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.event("command.fired", name="undo")
        telemetry.event("command.fired", name="undo")
        telemetry.event("syntax.used", name="bullets")
        counts = readout.usage_counts()
        assert counts["command.fired"] == 2
        assert readout.usage_counts(prefix="syntax.") == {"syntax.used": 1}

    def test_never_fired_is_the_discovery_gap(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.event("syntax.used")
        known = ["syntax.used", "mode.switch", "command.fired"]
        assert readout.never_fired(known) == ["mode.switch", "command.fired"]

    def test_attr_split(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.event("entry.dictation", source="hotkey")
        telemetry.event("entry.dictation", source="hotkey")
        telemetry.event("entry.dictation", source="tray")
        split = readout.attr_split("entry.dictation", "source")
        assert split == {"hotkey": 2, "tray": 1}

    def test_clear(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.event("command.fired")
        assert sink.clear() == 1
        assert sink.read() == []


@pytest.fixture
def _clean_registry():
    syntax.clear()
    yield
    syntax.clear()


def _feature(name: str, mark: str | None):
    """A feature that appends `mark` (so it changes the text) or is a no-op."""

    def fn(text: str, _ctx) -> str:
        return f"{text}{mark}" if mark else text

    return SyntaxFeature(name=name, apply=fn)


class TestSyntaxInstrumentation:
    """The on_fire seam: a feature is 'used' only when it changes the text, and
    only the daemon (which passes the hook) records it — the eval path stays
    pure so it never pollutes the event log."""

    def test_on_fire_only_when_text_changes(self, _clean_registry):
        syntax.register(_feature("changer", mark="!"))
        syntax.register(_feature("noop", mark=None))
        fired: list[str] = []
        apply_syntax("hello", on_fire=fired.append)
        assert fired == ["changer"]

    def test_no_callback_is_silent(self, _clean_registry, tmp_path, monkeypatch):
        # the eval path calls apply_syntax with no hook → no events written
        _isolate(tmp_path, monkeypatch)
        syntax.register(_feature("changer", mark="!"))
        assert apply_syntax("hello") == "hello!"
        assert sink.read() == []

    def test_postprocess_forwards_the_hook(self, _clean_registry):
        syntax.register(_feature("changer", mark="X"))
        fired: list[str] = []
        postprocess("hi", on_syntax_fire=fired.append)
        assert fired == ["changer"]

    def test_postprocess_records_via_telemetry(
        self, _clean_registry, tmp_path, monkeypatch
    ):
        # the daemon's actual wiring: postprocess → telemetry.event("syntax.used")
        _isolate(tmp_path, monkeypatch)
        syntax.register(_feature("bullets", mark="•"))
        postprocess("hi", on_syntax_fire=lambda n: telemetry.event("syntax.used", name=n))
        rows = sink.read(name="syntax.used")
        assert len(rows) == 1
        assert rows[0][2] == {"name": "bullets"}
