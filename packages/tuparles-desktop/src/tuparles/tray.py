"""Notification-area presence: the daemon's perch when the bubble sleeps.

A mini-waveform glyph in the topbar, tinted by state (idle, recording,
processing — same palette as the bubble). The menu is the mouse-side of
the product: start/stop without the hotkey, recover past transcripts,
quit cleanly. History entries copy to clipboard on click — never typed
into focus, because focus just moved to a menu.
"""

import math
from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from tuparles import history, settings, takes
from tuparles.bugreport import version_label
from tuparles.delivery import to_clipboard

_IDLE = QColor(205, 214, 244)
# Recording/processing tint by engine, matching the bubble: green=GPU, blue=CPU.
_GPU = QColor(122, 199, 130)
_CPU = QColor(122, 162, 247)
# The persistent CPU-fallback resting tint (#131): a desaturated, dimmer blue the
# idle glyph wears the WHOLE time the engine is on the CPU rung — not a hue switch
# (blue already is the CPU identity) but a brightness/saturation drop, per the
# house colour doctrine. So a glance at an at-rest tray still says "slower
# silicon", where the neutral _IDLE used to hide a two-day post-suspend fallback.
_CPU_IDLE = QColor(96, 112, 156)
# Dev raw-audio capture indicator: a steady red dot on the glyph the whole time
# it's armed, so "your unredacted voice is being written to disk" is never silent.
_DEV_DOT = QColor(243, 139, 168)

_REST_HEIGHTS = (0.45, 0.85, 0.60)  # the glyph's pose when not animating
# Icon churn budget. On SNI trays (GNOME appindicator, KDE) every setIcon is an
# org.kde.StatusNotifierItem.NewIcon D-Bus signal — Qt emits it unconditionally,
# with no comparison to the previous icon — and the shell then fetches and
# decodes a fresh pixmap ON ITS MAIN THREAD. The old 10 Hz breath, running
# around the clock even at rest, grew gnome-shell's heap ~450 MiB/12 h and
# stalled its main loop 0.4-0.7 s every ~11 s (system-wide freezes, stuck key
# repeat). So: rest never animates (zero updates, the timer is off). A live
# take steps at 8 Hz through a handful of cached frames — a take lasts seconds,
# so the shell sees a few dozen pixmaps, and the bars visibly follow speech.
# macOS menu-bar icons are local pixmaps, not a D-Bus round trip, so the same
# rate is cheap there and is what makes the glyph feel alive.
_TRAY_FRAME_MS = 125  # 8 Hz, and ONLY while recording/decoding
# The live animation is a loop of a few precomputed poses, not a free-running
# phase: frames repeat exactly, so they cache (no paint per tick) and dedupe.
# 6 frames at 2 Hz = one 3 s cycle, close to the old breath's ~2.2 s period.
_ANIM_FRAMES = 6
_ANIMATED_STATES = frozenset({"recording", "processing"})
# Every reachable frame: rest x (6 state colours) + 2 live states x 6 frames x
# (2 engines), each with/without the dev dot = 60. The bound is a backstop
# against a future key that grows without limit, not a working-set size.
_ICON_CACHE_MAX = 64
_HISTORY_SHOWN = 8
_LABEL_CHARS = 46
_README_URL = "https://github.com/PLNech/TuParles#readme"


def _glyph(
    color: QColor, heights=_REST_HEIGHTS, lift: float = 0.0, dev_dot: bool = False
) -> QIcon:
    """Three rounded bars in `color`. `heights` (0..1 each) and `lift` (a small
    vertical bob, in px) are what the breathing animation modulates per frame.
    `dev_dot` overlays a steady red dot (top-right) while raw-audio capture is
    armed — a persistent, unmissable "recording your voice to disk" badge (#8)."""
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
    if dev_dot:
        p.setBrush(_DEV_DOT)
        p.drawEllipse(QRectF(15.0, 1.0, 6.0, 6.0))  # top-right, clear of the bars
    p.end()
    return QIcon(pm)


def state_color(state: str, backend: str) -> QColor:
    """Tray glyph colour for (pipeline state, live engine). Pure → headless-tested.

    Hue is the engine IDENTITY (green=GPU, blue=CPU), matching the bubble. The
    degraded CPU fallback is signalled *persistently* — even at idle — by a
    desaturated, dimmer blue (`_CPU_IDLE`), so a glance at an at-rest tray still
    says "you're on the slower silicon", not just the one-shot green→blue flash
    during an active take (#131). The operator ran two days on the CPU rung after
    a suspend precisely because idle looked neutral. Idle on GPU stays the neutral
    resting colour — there's nothing to flag."""
    on_cpu = backend == "cpu"
    if state == "recording":
        return QColor(_CPU if on_cpu else _GPU)  # full engine colour: clearly live
    if state == "processing":
        color = QColor(_CPU if on_cpu else _GPU)
        color.setAlpha(160)  # dimmer engine colour: "working, settling"
        return color
    # idle: GPU rests neutral; the CPU fallback keeps its persistent muted signal.
    return QColor(_CPU_IDLE) if on_cpu else QColor(_IDLE)


def frame_pose(
    kind: str, frame: int, level: float = 0.0
) -> tuple[tuple[float, ...], float]:
    """(bar heights, vertical lift) for animation frame `frame` of `kind`. Pure
    and periodic over `_ANIM_FRAMES`, so a frame index fully names a picture.

    "recording": the creature leans in — bigger, phase-shifted bars + a slight
    bob. "processing": a bright pulse travelling across the three bars. Anything
    else ("rest"): the static rest pose."""
    theta = 2 * math.pi * (frame % _ANIM_FRAMES) / _ANIM_FRAMES
    if kind == "recording":
        # The breath stays, so a quiet moment still moves. The mic level rides
        # on top: a spoken syllable lifts the bars, silence lets them rest.
        # `level` is the recorder's 0..1 RMS, already perceptually mapped.
        speech = max(0.0, min(1.0, level))
        heights = tuple(
            min(
                0.95,
                0.28
                + 0.22 * (0.5 + 0.5 * math.sin(theta + i * 2 * math.pi / 3))
                + 0.45 * speech,
            )
            for i in range(3)
        )
        return heights, 0.9 * math.sin(theta)
    if kind == "processing":
        center = 3 * (frame % _ANIM_FRAMES) / _ANIM_FRAMES
        heights = tuple(
            0.30
            + 0.55 * math.exp(-(min(abs(i - center), 3 - abs(i - center)) ** 2) / 0.6)
            for i in range(3)
        )
        return heights, 0.0
    return _REST_HEIGHTS, 0.0


class Tray(QObject):
    toggle_requested = Signal()
    restart_requested = Signal()
    quit_requested = Signal()
    view_changed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        backend_source: Callable[[], str] | None = None,
        level_source: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(parent)
        # Pull source for the ambient engine colour ("gpu"|"cpu"), as the bubble.
        self._backend_source = backend_source or (lambda: "gpu")
        # Mic level, 0..1, so the recording glyph follows speech instead of
        # breathing on its own. None on a caller that has no recorder.
        self._level_source = level_source
        self._state = "idle"
        self._frame = 0  # index into the live animation loop (0.._ANIM_FRAMES-1)
        self._animate = bool(settings.get("tray_animation"))
        self._dev_dot = takes.dev_recording_enabled()

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
        # The running build, visible: after "Redémarrer" the user can check this
        # line changed (commit hash on a dev checkout) instead of wondering
        # whether the restart actually picked up new code. Resolved at startup,
        # so the label is the code that's running, not the code on disk.
        self._version_act = self._menu.addAction(f"TuParles {version_label()}")
        self._version_act.setEnabled(False)
        self._menu.addAction("À propos").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_README_URL))
        )
        self._menu.addAction("Redémarrer").triggered.connect(
            self.restart_requested.emit
        )
        self._menu.addAction("Quitter").triggered.connect(self.quit_requested.emit)

        # The frame on screen, by key, so an unchanged frame never re-reaches
        # setIcon (Qt would re-emit NewIcon for it regardless). The key names
        # the picture: (pose kind, frame index, colour rgba, dev dot).
        self._icon_cache: OrderedDict[tuple, QIcon] = OrderedDict()
        self._current_key = self._frame_key()
        self._current_icon = self._icon_for(self._current_key)
        self._tray = QSystemTrayIcon(self._current_icon, self)
        self._tray.setContextMenu(self._menu)
        self._tooltip = ""
        self._refresh_tooltip()
        self._tray.show()

        # The live-take animation: one timer, created once, that steps the frame
        # loop. It runs ONLY while recording/decoding with animation on; rest is
        # a single static glyph set on state change (see _TRAY_FRAME_MS).
        self._timer = QTimer(self)
        self._timer.setInterval(_TRAY_FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._sync_timer()

    def _pose_kind(self) -> str:
        if self._animate and self._state in _ANIMATED_STATES:
            return self._state
        return "rest"

    def _frame_key(self) -> tuple:
        """What the glyph should show right now, as a hashable key. Reads only
        memory (the backend pull is an attribute read) — never settings.json,
        so a tick costs no file I/O."""
        kind = self._pose_kind()
        frame = self._frame if kind != "rest" else 0
        color = state_color(self._state, self._backend_source())
        # Four steps of loudness. Enough for the bars to answer speech, few
        # enough that the icon cache stays inside _ICON_CACHE_MAX.
        level = 0
        if kind == "recording" and self._level_source is not None:
            level = max(0, min(3, int(self._level_source() * 4)))
        return kind, frame, color.rgba(), self._dev_dot, level

    def _icon_for(self, key: tuple) -> QIcon:
        """The cached QIcon for `key`, painted once on first sight. LRU-bounded
        by _ICON_CACHE_MAX as a backstop; the reachable set is smaller."""
        icon = self._icon_cache.get(key)
        if icon is not None:
            self._icon_cache.move_to_end(key)
            return icon
        kind, frame, rgba, dev_dot, level = key
        heights, lift = frame_pose(kind, frame, level / 3)
        icon = _glyph(QColor.fromRgba(rgba), heights, lift, dev_dot=dev_dot)
        self._icon_cache[key] = icon
        while len(self._icon_cache) > _ICON_CACHE_MAX:
            self._icon_cache.popitem(last=False)
        return icon

    def _show(self) -> None:
        """Push the current frame to the tray iff it differs from what is
        already shown. The one and only setIcon call site."""
        key = self._frame_key()
        if key == self._current_key:
            return
        self._current_key = key
        self._current_icon = self._icon_for(key)
        self._tray.setIcon(self._current_icon)

    def _sync_timer(self) -> None:
        """Run the frame timer exactly when there is something to animate."""
        wanted = self._pose_kind() != "rest"
        if wanted and not self._timer.isActive():
            self._timer.start()
        elif not wanted and self._timer.isActive():
            self._timer.stop()

    def _refresh_tooltip(self) -> None:
        """Spell out dev capture in the tooltip whenever it's armed, so the red
        dot has words next to it on hover. Only re-sent when the text changes
        (a setToolTip is a NewToolTip D-Bus signal too)."""
        from tuparles.config import IS_MACOS

        chord = (
            "Option droit + Commande droit"
            if IS_MACOS
            else "Ctrl droit + Alt droit"
        )
        base = f"TuParles — {chord} pour dicter"
        if self._dev_dot:
            base += "\n⚠ Mode dev : audio brut (non masqué) enregistré sur le disque"
        if base != self._tooltip:
            self._tooltip = base
            self._tray.setToolTip(base)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % _ANIM_FRAMES
        self._show()

    def refresh(self) -> None:
        """Re-pull the ambient inputs (engine colour) and repaint only if the
        glyph actually changed. Cheap and idempotent: safe to call whenever a
        caller suspects the backend moved."""
        self._show()

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._frame = 0  # each live state starts its loop from the top
        self._state = state
        # Re-read the dev badge once per state change (a settings.json read), so
        # a take never starts with a stale "recording your voice" indicator.
        self._dev_dot = takes.dev_recording_enabled()
        self._toggle_act.setText(
            "Arrêter la dictée" if state == "recording" else "Dicter"
        )
        self._sync_timer()
        self._show()

    def on_final(self, _text: str) -> None:
        self._copy_act.setEnabled(True)
        self._rebuild_history()

    def apply_live_settings(self) -> None:
        """Re-read the settings the Réglages dialog can change and apply them
        without a restart (start/stop the live-take animation, repaint if the
        glyph changed). Wired to the dialog's `accepted` — the rest (mic, langs,
        casing, PII) is already read per-take, so this just covers the tray's
        own live state."""
        self._animate = bool(settings.get("tray_animation"))
        self._dev_dot = takes.dev_recording_enabled()
        self._sync_timer()
        self._refresh_tooltip()  # dev capture may have just been toggled
        self._show()  # reflect the change at once, if there is one

    def _open_settings(self) -> None:
        from tuparles.settings_ui import SettingsDialog

        self._settings_dialog = SettingsDialog()  # ref kept: GC-proof
        self._settings_dialog.accepted.connect(self.apply_live_settings)
        self._settings_dialog.show()
        self._settings_dialog.raise_()

    def _open_analytics(self) -> None:
        from tuparles.telemetry_dashboard import AnalyticsDialog

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
