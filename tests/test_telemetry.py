"""Telemetry primitives: events persist locally, the opt-out is a hard gate,
and the readout answers the discovery question."""

import pytest

from tuparles import history, syntax, telemetry
from tuparles.pipeline import postprocess
from tuparles.syntax import SyntaxFeature, apply_syntax
from tuparles.telemetry import introspect, readout, sink


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
        postprocess(
            "hi", on_syntax_fire=lambda n: telemetry.event("syntax.used", name=n)
        )
        rows = sink.read(name="syntax.used")
        assert len(rows) == 1
        assert rows[0][2] == {"name": "bullets"}


class TestIntrospect:
    """The nlp-over-introspection bridge: utterances through the nlp engine,
    events through the readout — both local, both degrading gracefully."""

    def test_usage_summary_is_pure_stdlib(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        telemetry.event("entry.dictation", source="hotkey")
        telemetry.event("entry.dictation", source="tray")
        telemetry.event("entry.dictation", source="hotkey")
        telemetry.event("command.fired", name="undo")
        telemetry.event("syntax.used", name="bullets")
        summary = introspect.usage_summary()
        assert summary["total"] == 5
        assert summary["entry_split"] == {"hotkey": 2, "tray": 1}
        assert summary["commands"] == {"undo": 1}  # by action name, not event name
        assert summary["syntax_used"] == {"bullets": 1}

    def test_utterance_tags_over_history(self, tmp_path, monkeypatch):
        if not introspect.nlp_available():
            pytest.skip("nlp extras not installed")
        _isolate(tmp_path, monkeypatch)
        history.record("parlons de RequestOptions et de faceting")
        history.record("encore RequestOptions dans le code")
        tags = introspect.utterance_tags(top=10)
        assert isinstance(tags, list) and tags
        surfaces = {surface.lower() for surface, _w in tags}
        assert "requestoptions" in surfaces
        assert all(0.0 <= w <= 1.0 for _s, w in tags)

    def test_empty_history_is_empty_not_a_crash(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert introspect.utterance_tags() == []
        assert introspect.utterance_keyphrases() == []
        assert introspect.usage_summary()["total"] == 0


class TestDashboardHtml:
    """The dialog's three views are built by pure HTML functions (no QWidget),
    so we test the rendering logic without a QApplication — matching the
    project's grandfathered UI-test boundary. The dashboard *module* still
    imports PySide6 at top, so skip on the Qt-less CI runners."""

    @pytest.fixture(autouse=True)
    def _need_qt(self):
        pytest.importorskip("PySide6")

    def test_usage_html_shows_counts_and_discovery_gap(
        self, _clean_registry, tmp_path, monkeypatch
    ):
        from tuparles.telemetry import dashboard

        _isolate(tmp_path, monkeypatch)
        syntax.register(_feature("bullets", mark="•"))  # registered, never fired
        telemetry.event("command.fired", name="undo")
        telemetry.event("entry.dictation", source="hotkey")
        html = dashboard._usage_html()
        assert "undo" in html and "hotkey" in html
        assert "Jamais utilisé" in html and "bullets" in html  # the discovery gap

    def test_usage_html_empty_state(self, tmp_path, monkeypatch):
        from tuparles.telemetry import dashboard

        _isolate(tmp_path, monkeypatch)
        assert "Aucune donnée" in dashboard._usage_html()

    def test_code_html_renders_or_prompts(self, tmp_path, monkeypatch):
        from tuparles.telemetry import dashboard

        # cached EDA JSON lives in the repo, so this renders the real analysis;
        # either way it must be a non-crashing string under the right heading.
        html = dashboard._code_html()
        assert "Ton code" in html or "Aucune analyse" in html


class _Recorder:
    recording = False

    def start(self) -> None:
        self.recording = True


class _Bubble:
    def start_recording(self) -> None:
        pass


class TestDaemonEntryInstrumentation:
    """The entry-path wiring (toggle_from_tray/hotkey → event in the *start*
    branch) is the riskiest new code, and the seam/HTML tests don't touch it.
    Drive a stubbed Controller under offscreen Qt to pin the source attr.

    command.fired is NOT covered here — _run_command calls execute_command,
    which fires real keystrokes; it awaits a live daemon run.
    """

    @pytest.fixture(autouse=True)
    def _need_qt(self):
        pytest.importorskip("PySide6")

    def _controller(self, monkeypatch):
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
        monkeypatch.setattr("tuparles.daemon.IS_WAYLAND", False)
        from PySide6.QtWidgets import QApplication

        from tuparles.daemon import Bridge, Controller

        QApplication.instance() or QApplication([])  # one app, offscreen
        return Controller(
            engine=object(),  # no supports_partials → no partials thread
            recorder=_Recorder(),
            bubble=_Bubble(),
            bridge=Bridge(),
        )

    def test_tray_entry_tagged(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        self._controller(monkeypatch).toggle_from_tray()
        rows = sink.read(name="entry.dictation")
        assert rows and rows[0][2] == {"source": "tray"}

    def test_hotkey_entry_tagged(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        self._controller(monkeypatch).toggle_from_hotkey()
        rows = sink.read(name="entry.dictation")
        assert rows and rows[0][2] == {"source": "hotkey"}
