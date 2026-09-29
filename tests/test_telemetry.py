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
        from tuparles import telemetry_dashboard as dashboard

        _isolate(tmp_path, monkeypatch)
        syntax.register(_feature("bullets", mark="•"))  # registered, never fired
        telemetry.event("command.fired", name="undo")
        telemetry.event("entry.dictation", source="hotkey")
        html = dashboard._usage_html()
        assert "undo" in html and "hotkey" in html
        assert "Jamais utilisé" in html and "bullets" in html  # the discovery gap

    def test_usage_html_empty_state(self, tmp_path, monkeypatch):
        from tuparles import telemetry_dashboard as dashboard

        _isolate(tmp_path, monkeypatch)
        assert "Aucune donnée" in dashboard._usage_html()

    def test_code_html_renders_or_prompts(self, tmp_path, monkeypatch):
        from tuparles import telemetry_dashboard as dashboard

        # cached EDA JSON lives in the repo, so this renders the real analysis;
        # either way it must be a non-crashing string under the right heading.
        html = dashboard._code_html()
        assert "Ton code" in html or "Aucune analyse" in html


class TestDashboardAsync:
    @pytest.fixture(autouse=True)
    def _qt(self, monkeypatch):
        pytest.importorskip("PySide6")
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])

    def _until(self, condition):
        import time

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        pytest.fail("dashboard worker did not finish")

    def test_lazy_render_keeps_dialog_responsive(self, monkeypatch):
        from threading import Event

        from tuparles import telemetry_dashboard as dashboard

        started, release = Event(), Event()
        calls = []

        def slow_usage():
            calls.append("usage")
            started.set()
            assert release.wait(3)
            return "<p>Usage loaded</p>"

        monkeypatch.setattr(dashboard, "enabled", lambda: True)
        monkeypatch.setattr(dashboard, "_usage_html", slow_usage)
        monkeypatch.setattr(dashboard, "_voice_html", lambda: "<p>Voice loaded</p>")
        monkeypatch.setattr(dashboard, "_code_html", lambda: "<p>Code loaded</p>")
        dialog = dashboard.AnalyticsDialog()
        try:
            assert "Chargement" in dialog._views[0].toPlainText()
            assert calls == []  # construction did not run any renderer
            self._until(started.is_set)
            assert "Chargement" in dialog._views[0].toPlainText()
            assert 1 not in dialog._workers  # inactive tabs are lazy
            dialog._tabs.setCurrentIndex(1)
            self._until(lambda: "Voice loaded" in dialog._views[1].toPlainText())
            dialog._tabs.setCurrentIndex(0)
            release.set()
            self._until(lambda: "Usage loaded" in dialog._views[0].toPlainText())
            assert calls == ["usage"]
        finally:
            release.set()
            dialog.close()

    @pytest.mark.parametrize("outcome", ["success", "failure", "close"])
    def test_voice_cloud_visible_while_keyphrases_pending(self, monkeypatch, outcome):
        from threading import Event

        from tuparles import telemetry_dashboard as dashboard

        started, release = Event(), Event()

        def slow_phrases(**kwargs):
            started.set()
            assert release.wait(3)
            if outcome == "failure":
                raise RuntimeError("private exception detail")
            return [("phrase complète", 0.1)]

        monkeypatch.setattr(dashboard, "enabled", lambda: True)
        monkeypatch.setattr(introspect, "nlp_available", lambda: True)
        monkeypatch.setattr(introspect, "utterance_tags", lambda **kw: [("bonjour", 1)])
        monkeypatch.setattr(introspect, "utterance_keyphrases", slow_phrases)
        dialog = dashboard.AnalyticsDialog()
        dialog._tabs.setCurrentIndex(1)
        try:
            self._until(
                lambda: started.is_set() and "bonjour" in dialog._views[1].toPlainText()
            )
            assert 1 not in dialog._loaded
            assert "Chargement des expressions" in dialog._views[1].toPlainText()
            if outcome == "close":
                dialog.close()
            release.set()
            self._until(lambda: 1 not in dialog._workers)
            content = dialog._views[1].toPlainText()
            assert "bonjour" in content
            if outcome == "success":
                assert "phrase complète" in content
                assert "Chargement" not in content
                assert 1 in dialog._loaded
            elif outcome == "failure":
                assert "Impossible" in content
                assert "Chargement" not in content
                assert "private exception" not in content
            else:
                assert "phrase complète" not in content
                assert 1 not in dialog._loaded
        finally:
            release.set()
            self._until(lambda: 1 not in dialog._workers)
            dialog.close()

    def test_late_result_after_close_is_ignored(self, monkeypatch):
        from threading import Event

        from tuparles import telemetry_dashboard as dashboard

        started, release = Event(), Event()

        def slow_usage():
            started.set()
            assert release.wait(3)
            return "<p>Late result</p>"

        monkeypatch.setattr(dashboard, "enabled", lambda: True)
        monkeypatch.setattr(dashboard, "_usage_html", slow_usage)
        dialog = dashboard.AnalyticsDialog()
        try:
            self._until(started.is_set)
            dialog.close()
            release.set()
            self._until(lambda: not dialog._workers)
            assert "Late result" not in dialog._views[0].toPlainText()
            assert dialog._loaded == set()
        finally:
            release.set()
            dialog.close()

    def test_late_result_after_reject_is_ignored(self, monkeypatch):
        from threading import Event

        from tuparles import telemetry_dashboard as dashboard

        started, release = Event(), Event()

        def slow_usage():
            started.set()
            assert release.wait(3)
            return "<p>Late result</p>"

        monkeypatch.setattr(dashboard, "enabled", lambda: True)
        monkeypatch.setattr(dashboard, "_usage_html", slow_usage)
        dialog = dashboard.AnalyticsDialog()
        try:
            self._until(started.is_set)
            dialog.reject()  # Escape uses QDialog's reject/done path
            assert dialog._closed
            release.set()
            self._until(lambda: not dialog._workers)
            assert "Late result" not in dialog._views[0].toPlainText()
        finally:
            release.set()
            dialog.close()

    def test_deleted_dialog_during_render(self, monkeypatch):
        from threading import Event

        from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
        from shiboken6 import isValid

        from tuparles import telemetry_dashboard as dashboard

        started, release = Event(), Event()

        def slow_usage():
            started.set()
            assert release.wait(3)
            return "<p>Late result</p>"

        monkeypatch.setattr(dashboard, "enabled", lambda: True)
        monkeypatch.setattr(dashboard, "_usage_html", slow_usage)
        dialog = dashboard.AnalyticsDialog()
        try:
            self._until(started.is_set)
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert not isValid(dialog)
        finally:
            release.set()
            assert QThreadPool.globalInstance().waitForDone(3000)
            self.app.processEvents()  # queued signal cannot call a deleted receiver

    def test_reopen_reads_new_events(self, tmp_path, monkeypatch):
        from tuparles import telemetry_dashboard as dashboard

        _isolate(tmp_path, monkeypatch)
        first = dashboard.AnalyticsDialog()
        self._until(lambda: 0 in first._loaded)
        assert "Aucune donnée" in first._views[0].toPlainText()
        first.close()

        telemetry.event("command.fired", name="undo")
        second = dashboard.AnalyticsDialog()
        try:
            self._until(lambda: 0 in second._loaded)
            assert "undo" in second._views[0].toPlainText()
        finally:
            second.close()

    def test_render_failure_replaces_loading_state(self, monkeypatch):
        from tuparles import telemetry_dashboard as dashboard

        def broken_usage():
            raise RuntimeError("private detail must stay out of the UI")

        monkeypatch.setattr(dashboard, "enabled", lambda: True)
        monkeypatch.setattr(dashboard, "_usage_html", broken_usage)
        dialog = dashboard.AnalyticsDialog()
        try:
            self._until(
                lambda: not dialog._workers
                and "Impossible" in dialog._views[0].toPlainText()
            )
            assert "private detail" not in dialog._views[0].toPlainText()
        finally:
            dialog.close()


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
