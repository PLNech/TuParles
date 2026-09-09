"""Réglages must scroll, not squash.

The dialog was once a single flat QVBoxLayout with no scroll area: its natural
height ran well past a thousand pixels, so once the window manager capped the
window Qt compressed every row past its minimum and the word-wrapped hints
printed on top of each other. This is the regression guard — offscreen has no
window manager, so the test imposes the cramped size itself.
"""

import pytest

# The size from the original bug report, where the text overlapped.
CRAMPED = (738, 578)


def _qt(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _squashed(dialog) -> list[str]:
    """Visible widgets laid out shorter than they can legibly be."""
    from PySide6.QtWidgets import QWidget

    bad = []
    for widget in dialog.findChildren(QWidget):
        if not widget.isVisible():
            continue
        needed = widget.minimumSizeHint().height()
        if needed > 0 and widget.height() < needed:
            text = widget.text()[:40] if hasattr(widget, "text") else ""
            bad.append(f"{type(widget).__name__}({text!r}) {widget.height()}<{needed}")
    return bad


class TestNoSquash:
    def test_every_page_survives_a_cramped_window(self, tmp_path, monkeypatch):
        app = _qt(tmp_path, monkeypatch)
        from tuparles.settings_ui import SettingsDialog

        dlg = SettingsDialog()
        dlg.resize(*CRAMPED)
        dlg.show()
        app.processEvents()

        for row in range(dlg._nav.count()):
            dlg._nav.setCurrentRow(row)
            app.processEvents()
            assert not _squashed(dlg), (
                f"page {dlg._nav.item(row).text()!r} squashes its widgets"
            )

    def test_pages_are_scrollable_not_fixed(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from PySide6.QtWidgets import QScrollArea

        from tuparles.settings_ui import SettingsDialog

        dlg = SettingsDialog()
        assert dlg._pages.count() == dlg._nav.count() > 0
        for row in range(dlg._pages.count()):
            page = dlg._pages.widget(row)
            assert isinstance(page, QScrollArea)
            # Without widgetResizable the inner widget keeps its size hint and
            # the area clips instead of scrolling — and wrapped labels, which
            # need a definite width, mis-measure their height.
            assert page.widgetResizable()

    def test_nav_selects_the_matching_page(self, tmp_path, monkeypatch):
        app = _qt(tmp_path, monkeypatch)
        from tuparles.settings_ui import SettingsDialog

        dlg = SettingsDialog()
        dlg.show()
        for row in range(dlg._nav.count()):
            dlg._nav.setCurrentRow(row)
            app.processEvents()
            assert dlg._pages.currentIndex() == row


class TestSettingsStillRoundTrip:
    """Re-homing widgets across pages must not lose a single setting."""

    def test_every_page_widget_is_saved(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles import settings
        from tuparles.settings_ui import SettingsDialog

        dlg = SettingsDialog()
        dlg._trim_silence.setChecked(True)  # Décodage page
        dlg._tray_anim.setChecked(False)  # Bulle page
        dlg._clipboard_restore.setChecked(True)  # Écriture page
        dlg._ribbon_lines.setValue(3)
        dlg._save()

        assert settings.get("trim_silence") is True
        assert settings.get("tray_animation") is False
        assert settings.get("clipboard_restore") is True
        assert settings.get("bubble_lines") == 3

    def test_mic_is_stored_by_id_not_label(self, tmp_path, monkeypatch):
        _qt(tmp_path, monkeypatch)
        from tuparles import audio, settings
        from tuparles.settings_ui import SettingsDialog

        monkeypatch.setattr(
            audio,
            "list_mics",
            lambda refresh=False: [
                {
                    "id": "bluez_input.AA_BB.0",
                    "label": "Studio Headset",
                    "default": False,
                    "kind": "pulse",
                }
            ],
        )
        import tuparles.settings_ui as ui

        monkeypatch.setattr(ui, "list_mics", audio.list_mics)

        dlg = SettingsDialog()
        i = dlg._mic.findData("bluez_input.AA_BB.0")
        assert i >= 0, "the pulse source is not offered"
        assert dlg._mic.itemText(i) == "Studio Headset"  # human label shown…
        dlg._mic.setCurrentIndex(i)
        dlg._save()
        assert settings.get("input_device") == "bluez_input.AA_BB.0"  # …id stored
