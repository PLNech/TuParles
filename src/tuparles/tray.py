"""Notification-area presence: the daemon's perch when the bubble sleeps.

A mini-waveform glyph in the topbar, tinted by state (idle, recording,
processing — same palette as the bubble). The menu is the mouse-side of
the product: start/stop without the hotkey, recover past transcripts,
quit cleanly. History entries copy to clipboard on click — never typed
into focus, because focus just moved to a menu.
"""

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from tuparles import history, settings
from tuparles.delivery import to_clipboard

_IDLE = QColor(205, 214, 244)
_RECORDING = QColor(122, 162, 247)  # bubble's accent
_PROCESSING = QColor(127, 132, 156)

_BAR_HEIGHTS = (0.45, 0.85, 0.60)  # the bubble's waveform, frozen mid-breath
_HISTORY_SHOWN = 8
_LABEL_CHARS = 46
_README_URL = "https://github.com/PLNech/TuParles#readme"


def _glyph(color: QColor) -> QIcon:
    pm = QPixmap(22, 22)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    bar_w, gap = 4, 3
    x = (22 - (bar_w * 3 + gap * 2)) / 2
    for h in _BAR_HEIGHTS:
        half = h * 9
        p.drawRoundedRect(QRectF(x, 11 - half, bar_w, half * 2), 2, 2)
        x += bar_w + gap
    p.end()
    return QIcon(pm)


class Tray(QObject):
    toggle_requested = Signal()
    restart_requested = Signal()
    quit_requested = Signal()
    view_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icons = {
            "idle": _glyph(_IDLE),
            "recording": _glyph(_RECORDING),
            "processing": _glyph(_PROCESSING),
        }

        self._menu = QMenu()
        self._toggle_act = self._menu.addAction("Dicter")
        self._toggle_act.triggered.connect(self.toggle_requested.emit)

        self._copy_act = self._menu.addAction("Copier la dernière")
        self._copy_act.triggered.connect(self._copy_last)
        self._copy_act.setEnabled(history.last() is not None)

        self._hist_menu = self._menu.addMenu("Historique")
        # GNOME tray menus travel over DBus (AppIndicator), which makes lazy
        # population doubly cursed: aboutToShow arrives unreliably, AND a
        # rebuild while the menu is displayed invalidates the exported
        # layout — the submenu flashes and closes. So: never touch the menu
        # on show. Build eagerly, refresh only when a transcript lands, and
        # only if content actually changed.
        self._hist_shown: list[tuple[str, str]] = []
        self._rebuild_history()

        self._settings_act = self._menu.addAction("Réglages…")
        self._settings_act.triggered.connect(self._open_settings)

        self._full_act = self._menu.addAction("Affichage complet")
        self._full_act.setCheckable(True)
        self._full_act.setChecked(settings.get("view") == "full")
        self._full_act.toggled.connect(self._on_view_toggled)

        self._menu.addSeparator()
        self._menu.addAction("À propos").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_README_URL))
        )
        self._menu.addAction("Redémarrer").triggered.connect(
            self.restart_requested.emit
        )
        self._menu.addAction("Quitter").triggered.connect(self.quit_requested.emit)

        self._tray = QSystemTrayIcon(self._icons["idle"], self)
        self._tray.setToolTip("TuParles — Ctrl droit + Alt droit pour dicter")
        self._tray.setContextMenu(self._menu)
        self._tray.show()

    def set_state(self, state: str) -> None:
        self._tray.setIcon(self._icons.get(state, self._icons["idle"]))
        self._toggle_act.setText(
            "Arrêter la dictée" if state == "recording" else "Dicter"
        )

    def on_final(self, _text: str) -> None:
        self._copy_act.setEnabled(True)
        self._rebuild_history()

    def _open_settings(self) -> None:
        from tuparles.settings_ui import SettingsDialog

        self._settings_dialog = SettingsDialog()  # ref kept: GC-proof
        self._settings_dialog.show()
        self._settings_dialog.raise_()

    def _on_view_toggled(self, checked: bool) -> None:
        mode = "full" if checked else "minimal"
        settings.put("view", mode)
        self.view_changed.emit(mode)

    def _copy_last(self) -> None:
        text = history.last()
        if text:
            to_clipboard(text)

    def _rebuild_history(self) -> None:
        entries = history.recent(_HISTORY_SHOWN)
        if entries == self._hist_shown:
            return
        self._hist_shown = entries
        self._hist_menu.clear()
        if not entries:
            self._hist_menu.addAction("(vide)").setEnabled(False)
        for _ts, text in entries:
            label = text if len(text) <= _LABEL_CHARS else text[:_LABEL_CHARS] + "…"
            self._hist_menu.addAction(
                label, lambda t=text: to_clipboard(t)
            )
