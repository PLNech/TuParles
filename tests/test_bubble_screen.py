"""Bubble multi-monitor placement (settings "bubble_screen") and the Réglages
picker that writes it. Offscreen Qt, skipped where Qt is absent (CI)."""

import pytest


def _qt(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])


class TestTargetScreen:
    def _bubble(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles.ui import Bubble

        return Bubble(level_source=lambda: 0.0)

    def test_default_is_primary(self, tmp_path, monkeypatch):
        bubble = self._bubble(tmp_path, monkeypatch)  # importorskip first
        from PySide6.QtWidgets import QApplication

        assert bubble._target_screen() is QApplication.primaryScreen()

    def test_cursor_mode_resolves_a_screen(self, tmp_path, monkeypatch):
        from tuparles import settings

        bubble = self._bubble(tmp_path, monkeypatch)
        settings.put("bubble_screen", "cursor")
        assert bubble._target_screen() is not None  # cursor's screen or primary

    def test_unknown_pinned_screen_falls_back_to_primary(self, tmp_path, monkeypatch):
        bubble = self._bubble(tmp_path, monkeypatch)  # importorskip first
        from PySide6.QtWidgets import QApplication

        from tuparles import settings

        settings.put("bubble_screen", "Monitor-That-Was-Unplugged")
        # a vanished pinned monitor degrades to primary, never crashes a take
        assert bubble._target_screen() is QApplication.primaryScreen()

    def test_focus_mode_resolves_a_screen(self, tmp_path, monkeypatch):
        # focus follows the active window's screen on X11; offscreen has no
        # window manager, so it degrades to the cursor/primary screen — the
        # point is it ALWAYS resolves to a real screen, never None (no no-op).
        bubble = self._bubble(tmp_path, monkeypatch)
        from tuparles import settings

        settings.put("bubble_screen", "focus")
        assert bubble._target_screen() is not None

    def test_pinned_screen_source_overrides_setting(self, tmp_path, monkeypatch):
        # A BubbleGroup pins a bubble to a screen via screen_source, which must
        # win over whatever "bubble_screen" says.
        _qt(tmp_path, monkeypatch)
        from PySide6.QtWidgets import QApplication

        from tuparles import settings
        from tuparles.ui import Bubble

        primary = QApplication.primaryScreen()
        settings.put("bubble_screen", "cursor")
        bubble = Bubble(level_source=lambda: 0.0, screen_source=lambda: primary)
        assert bubble._target_screen() is primary


class TestResolveScreens:
    def test_single_mode_is_one_screen(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles.ui import resolve_screens

        assert len(resolve_screens("primary")) == 1

    def test_all_mode_covers_every_screen(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from PySide6.QtWidgets import QApplication

        from tuparles.ui import resolve_screens

        # "all" mirrors on every connected monitor (≥1, == the screen count).
        assert len(resolve_screens("all")) == len(QApplication.screens())


class TestBubbleGroup:
    def _group(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles.ui import BubbleGroup

        return BubbleGroup(level_source=lambda: 0.0)

    def test_start_recording_lights_active_bubbles(self, tmp_path, monkeypatch):
        group = self._group(tmp_path, monkeypatch)
        group.start_recording()
        assert group._active  # at least one screen lit
        assert all(b._state == "recording" for b in group._active)

    def test_all_mode_lights_one_bubble_per_screen(self, tmp_path, monkeypatch):
        group = self._group(tmp_path, monkeypatch)
        from PySide6.QtWidgets import QApplication

        from tuparles import settings

        settings.put("bubble_screen", "all")
        group.start_recording()
        assert len(group._active) == len(QApplication.screens())

    def test_set_view_propagates_and_persists(self, tmp_path, monkeypatch):
        group = self._group(tmp_path, monkeypatch)
        group.start_recording()  # creates a pooled bubble
        group.set_view("minimal")
        assert group._view == "minimal"
        assert all(b._view == "minimal" for b in group._pool.values())

    def test_fanout_methods_never_raise(self, tmp_path, monkeypatch):
        group = self._group(tmp_path, monkeypatch)
        group.start_recording()
        group.set_partial("salut")
        group.start_processing()
        group.show_final("salut le monde")
        group.hide()  # the Wayland paste-hide slot
        group.cancel()


class TestBarColour:
    """The hue contract (#color): bars mean *which silicon* and hold that hue
    end to end — green only ever means GPU, blue only ever means CPU. "Landed"
    is a brightness lift, not a hue change (the old final-green broke this)."""

    def _bubble(self, tmp_path, monkeypatch, backend):
        _qt(tmp_path, monkeypatch)
        from tuparles.ui import Bubble

        return Bubble(level_source=lambda: 0.0, backend_source=lambda: backend)

    def test_cpu_stays_blue_every_state(self, tmp_path, monkeypatch):
        b = self._bubble(tmp_path, monkeypatch, "cpu")
        for state in ("recording", "processing", "final"):
            b._state = state
            c = b._bar_color()
            assert c.blue() > c.green() and c.blue() > c.red(), state  # blue-dominant

    def test_gpu_stays_green_every_state(self, tmp_path, monkeypatch):
        b = self._bubble(tmp_path, monkeypatch, "gpu")
        for state in ("recording", "processing", "final"):
            b._state = state
            c = b._bar_color()
            assert c.green() > c.blue() and c.green() > c.red(), state  # green-dominant

    def test_final_reads_as_brighter_not_a_new_hue(self, tmp_path, monkeypatch):
        b = self._bubble(tmp_path, monkeypatch, "cpu")
        b._state = "recording"
        rec = b._bar_color()
        b._state = "final"
        fin = b._bar_color()
        assert fin.lightness() > rec.lightness()  # landed = brighter, still blue

    def test_error_is_red(self, tmp_path, monkeypatch):
        b = self._bubble(tmp_path, monkeypatch, "gpu")
        b._state = "error"
        c = b._bar_color()
        assert c.red() > c.green() and c.red() > c.blue()


class TestScreenPicker:
    def test_save_persists_bubble_screen(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles import settings
        from tuparles.settings_ui import SettingsDialog

        dlg = SettingsDialog()
        i = dlg._screen.findData("cursor")
        assert i >= 0
        dlg._screen.setCurrentIndex(i)
        dlg._save()
        assert settings.get("bubble_screen") == "cursor"

    def test_picker_offers_focus_and_all(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles.settings_ui import SettingsDialog

        dlg = SettingsDialog()
        assert dlg._screen.findData("focus") >= 0
        assert dlg._screen.findData("all") >= 0
