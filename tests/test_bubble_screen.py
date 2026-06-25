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
        from PySide6.QtWidgets import QApplication

        bubble = self._bubble(tmp_path, monkeypatch)
        assert bubble._target_screen() is QApplication.primaryScreen()

    def test_cursor_mode_resolves_a_screen(self, tmp_path, monkeypatch):
        from tuparles import settings

        bubble = self._bubble(tmp_path, monkeypatch)
        settings.put("bubble_screen", "cursor")
        assert bubble._target_screen() is not None  # cursor's screen or primary

    def test_unknown_pinned_screen_falls_back_to_primary(self, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QApplication

        from tuparles import settings

        bubble = self._bubble(tmp_path, monkeypatch)
        settings.put("bubble_screen", "Monitor-That-Was-Unplugged")
        # a vanished pinned monitor degrades to primary, never crashes a take
        assert bubble._target_screen() is QApplication.primaryScreen()


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
