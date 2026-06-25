"""Notification-area presence: the daemon's perch when the bubble sleeps.

A mini-waveform glyph in the topbar, tinted by state (idle, recording,
processing — same palette as the bubble). The menu is the mouse-side of
the product: start/stop without the hotkey, recover past transcripts,
quit cleanly. History entries copy to clipboard on click — never typed
into focus, because focus just moved to a menu.
"""

import math
from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from tuparles import history, settings
from tuparles.delivery import to_clipboard

_IDLE = QColor(205, 214, 244)
# Recording/processing tint by engine, matching the bubble: green=GPU, blue=CPU.
_GPU = QColor(122, 199, 130)
_CPU = QColor(122, 162, 247)

_REST_HEIGHTS = (0.45, 0.85, 0.60)  # the glyph's pose when not animating
_TRAY_FPS_MS = 100  # ~10 Hz: a gentle breath without hammering the DBus tray
_HISTORY_SHOWN = 8
_LABEL_CHARS = 46
_README_URL = "https://github.com/PLNech/TuParles#readme"


def _glyph(color: QColor, heights=_REST_HEIGHTS, lift: float = 0.0) -> QIcon:
    """Three rounded bars in `color`. `heights` (0..1 each) and `lift` (a small
    vertical bob, in px) are what the breathing animation modulates per frame."""
    pm = QPixmap(22, 22)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    bar_w, gap = 4, 3
    x = (22 - (bar_w * 3 + gap * 2)) / 2
    cy = 11 - lift
    for h in heights:
        half = min(0.95, max(0.0, h)) * 9
        p.drawRoundedRect(QRectF(x, cy - half, bar_w, half * 2), 2, 2)
        x += bar_w + gap
    p.end()
    return QIcon(pm)


class Tray(QObject):
    toggle_requested = Signal()
    restart_requested = Signal()
    quit_requested = Signal()
    view_changed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        backend_source: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        # Pull source for the ambient engine colour ("gpu"|"cpu"), as the bubble.
        self._backend_source = backend_source or (lambda: "gpu")
        self._state = "idle"
        self._phase = 0.0  # advances each tick; drives the breath/pulse
        self._animate = bool(settings.get("tray_animation"))

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

        self._analytics_act = self._menu.addAction("Analytics…")
        self._analytics_act.triggered.connect(self._open_analytics)

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

        self._tray = QSystemTrayIcon(self._compose_icon(), self)
        self._tray.setToolTip("TuParles — Ctrl droit + Alt droit pour dicter")
        self._tray.setContextMenu(self._menu)
        self._tray.show()

        # The breath: one timer advances the phase and repaints the glyph. Only
        # runs when animation is on; otherwise the glyph is set on state change.
        self._timer = QTimer(self)
        self._timer.setInterval(_TRAY_FPS_MS)
        self._timer.timeout.connect(self._tick)
        if self._animate:
            self._timer.start()

    def _engine_color(self) -> QColor:
        return _GPU if self._backend_source() == "gpu" else _CPU

    def _state_color(self) -> QColor:
        if self._state == "recording":
            return self._engine_color()  # full engine colour: clearly "live"
        if self._state == "processing":
            color = QColor(self._engine_color())
            color.setAlpha(160)  # dimmer engine colour: "working, settling"
            return color
        return _IDLE

    def _pose(self) -> tuple[tuple[float, ...], float]:
        """(bar heights, vertical lift) for this frame. A calm breath at rest,
        a livelier undulation + bounce while recording, a travelling pulse
        while decoding. Returns the static rest pose when animation is off."""
        if not self._animate:
            return _REST_HEIGHTS, 0.0
        ph = self._phase
        if self._state == "recording":
            # the creature leans in: bigger, phase-shifted bars + a slight bob
            heights = tuple(
                0.42 + 0.45 * (0.5 + 0.5 * math.sin(ph * 1.3 + i * 1.1))
                for i in range(3)
            )
            return heights, 0.9 * math.sin(ph * 0.9)
        if self._state == "processing":
            # a bright pulse travelling across the three bars: "thinking"
            center = (ph * 0.7) % 3
            heights = tuple(
                0.30
                + 0.55
                * math.exp(-(min(abs(i - center), 3 - abs(i - center)) ** 2) / 0.6)
                for i in range(3)
            )
            return heights, 0.0
        # idle: a slow, shallow breath with a gentle bob — alive, at rest
        breath = 0.5 + 0.5 * math.sin(ph * 0.32)
        heights = tuple(b * (0.86 + 0.14 * breath) for b in _REST_HEIGHTS)
        return heights, 0.7 * math.sin(ph * 0.32)

    def _compose_icon(self) -> QIcon:
        heights, lift = self._pose()
        return _glyph(self._state_color(), heights, lift)

    def _tick(self) -> None:
        self._phase += 0.2  # advance the breath
        self._tray.setIcon(self._compose_icon())

    def set_state(self, state: str) -> None:
        self._state = state
        self._toggle_act.setText(
            "Arrêter la dictée" if state == "recording" else "Dicter"
        )
        if not self._animate:  # animated path repaints on the timer instead
            self._tray.setIcon(self._compose_icon())

    def on_final(self, _text: str) -> None:
        self._copy_act.setEnabled(True)
        self._rebuild_history()

    def apply_live_settings(self) -> None:
        """Re-read the settings the Réglages dialog can change and apply them
        without a restart (start/stop the breath, repaint now). Wired to the
        dialog's `accepted` — the rest (mic, langs, casing, PII) is already
        read per-take, so this just covers the tray's own live state."""
        self._animate = bool(settings.get("tray_animation"))
        if self._animate and not self._timer.isActive():
            self._timer.start()
        elif not self._animate and self._timer.isActive():
            self._timer.stop()
        self._tray.setIcon(self._compose_icon())  # reflect the change at once

    def _open_settings(self) -> None:
        from tuparles.settings_ui import SettingsDialog

        self._settings_dialog = SettingsDialog()  # ref kept: GC-proof
        self._settings_dialog.accepted.connect(self.apply_live_settings)
        self._settings_dialog.show()
        self._settings_dialog.raise_()

    def _open_analytics(self) -> None:
        from tuparles.telemetry.dashboard import AnalyticsDialog

        self._analytics_dialog = AnalyticsDialog()  # ref kept: GC-proof
        self._analytics_dialog.show()
        self._analytics_dialog.raise_()

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
            self._hist_menu.addAction(label, lambda t=text: to_clipboard(t))
