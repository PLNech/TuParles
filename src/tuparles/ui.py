"""The bubble: a tiny rounded always-on-top pill, the daemon's only face.

Design intent: tech-as-magic-that-fades-into-background. It appears when
you start speaking (live waveform + streaming transcript), breathes while
the GPU thinks, flashes the landed text, and dissolves. It never takes
focus — delivery types into whatever window the user was in, and the
bubble must not steal that.

All public methods assume the GUI thread (wire worker threads through
queued signal connections, see daemon.py).
"""

import math
import subprocess
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Slot,
)
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from tuparles import settings

WIDTH, HEIGHT = 460, 56
MAX_HEIGHT = 300  # full view stops growing here; older lines trim with …
V_PAD = 16  # full-view vertical text padding
MARGIN_BOTTOM = 64  # gap between bubble and screen bottom
BAR_COUNT, BAR_W, BAR_GAP = 18, 3, 3
FPS_MS = 33  # one repaint per Recorder level sample

_BG = QColor(17, 19, 27, 236)
_TEXT_LIVE = QColor(205, 214, 244)
_TEXT_DIM = QColor(127, 132, 156)
# Bars encode *which silicon* is live — green=GPU, blue=CPU (saturated) — and
# hold that hue from the first frame to the last: idle, recording, processing
# AND the final "landed" flash are all the SAME colour, so green only ever
# means GPU. "Landed" is signalled by *brightness* (a lift toward white, see
# `_brighten`), never by switching hue — a CPU take stays blue end to end.
# Error stays red.
_GPU = QColor(122, 199, 130)  # GPU active
_CPU = QColor(122, 162, 247)  # CPU/qwen fallback
_ACCENT = _CPU  # legacy alias: the pre-engine-colour default accent
_ERR = QColor(247, 118, 142)

_PLACEHOLDER = "Je t'écoute…"


# ── multi-monitor screen resolution (settings "bubble_screen") ──────────────
# One place both the single Bubble and the mirroring BubbleGroup resolve the
# setting, so a pin / cursor / focus / mirror choice can never mean two things.


def _screen_by_name(name: str):
    for s in QApplication.screens():
        if s.name() == name:
            return s
    return None  # pinned monitor unplugged


def _active_window_screen():
    """The QScreen holding the focused window, best-effort — for "focus" mode.

    X11 (and XWayland when the target is an X11 window): ask xdotool for the
    active window's geometry and map its centre to a screen. Native Wayland
    clients are invisible to xdotool, so this returns None there and the caller
    degrades to the cursor's screen — a reliable "where I'm working" proxy, never
    a silent no-op (a setting that quietly does nothing is worse than absent).
    Fire-and-forget: any failure → None. Short cap — runs on the GUI thread at
    take start (focus is calm then; normally a few ms)."""
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowgeometry", "--shell"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    geo: dict[str, int] = {}
    for line in out.splitlines():
        key, _, val = line.partition("=")
        val = val.strip()
        if val.lstrip("-").isdigit():
            geo[key.strip()] = int(val)
    if "X" not in geo or "Y" not in geo:
        return None
    # Aim at the window's centre: a window straddling two monitors maps to the
    # one it mostly sits on, not whichever owns its top-left pixel.
    cx = geo["X"] + geo.get("WIDTH", 0) // 2
    cy = geo["Y"] + geo.get("HEIGHT", 0) // 2
    return QApplication.screenAt(QPoint(cx, cy))


def resolve_screen(mode: str | None):
    """One `bubble_screen` mode → the single QScreen the bubble calls home.

    "cursor" → the mouse's screen; "focus" → the active window's screen (X11),
    degrading to the cursor's screen then primary; a QScreen name → that monitor
    if present; "primary"/"all"/unknown/unplugged → the primary screen."""
    if mode == "cursor":
        return QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
    if mode == "focus":
        return (
            _active_window_screen()
            or QApplication.screenAt(QCursor.pos())
            or QApplication.primaryScreen()
        )
    if mode and mode not in ("primary", "all"):
        return _screen_by_name(mode) or QApplication.primaryScreen()
    return QApplication.primaryScreen()


def resolve_screens(mode: str | None) -> list:
    """A `bubble_screen` mode → the SET of screens the bubble shows on. "all"
    mirrors on every monitor; every other mode lights exactly one."""
    if mode == "all":
        return list(QApplication.screens()) or [QApplication.primaryScreen()]
    return [resolve_screen(mode)]


def _brighten(color: QColor, t: float = 0.4) -> QColor:
    """Lerp a colour `t` of the way toward white. The final-flash bars use this
    so "landed" reads as a brighter pulse of the *same* backend hue (green stays
    GPU, blue stays CPU) instead of a hue change that'd falsely signal GPU."""
    return QColor(
        round(color.red() + (255 - color.red()) * t),
        round(color.green() + (255 - color.green()) * t),
        round(color.blue() + (255 - color.blue()) * t),
    )


# ── queue chips (#15) ───────────────────────────────────────────────────────
# A take in flight is "decoding" (the live backend hue); the instant it lands it
# flashes "delivered" (the same hue brightened — landed-is-brighter, never a hue
# switch, matching the main bubble's flash) then fades. Pure so the colour
# decision is headless-tested without a paint pass.

CHIP_D = 12  # chip diameter (px)
CHIP_GAP = 7  # between chips
CHIP_PAD = 11  # chip-strip inner padding
CHIP_H = 26  # strip height
CHIP_GAP_ABOVE = 10  # gap between the strip and the main bubble below it


def chip_color(state: str, base: QColor) -> QColor:
    """A queue chip's colour: the live backend hue while decoding, brightened
    toward white the moment it's delivered (same hue, brighter — so green never
    stops meaning GPU). Any unknown state reads as still-decoding."""
    return _brighten(base, 0.5) if state == "delivered" else base


class Bubble(QWidget):
    def __init__(
        self,
        level_source: Callable[[], float],
        view: str = "minimal",
        backend_source: Callable[[], str] | None = None,
        screen_source: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool,  # no taskbar entry
        )
        # Transparent corners + never steal focus from the dictation target.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(WIDTH, HEIGHT)
        self._trim_key: tuple | None = None  # _trim_to_fit memo (see below)
        self._trim_result = ""
        font = self.font()
        font.setPointSizeF(10.5)
        self.setFont(font)

        self._level_source = level_source
        # Pull source for the ambient engine colour ("gpu"|"cpu"); default to
        # gpu so older callers and tests keep the original look.
        self._backend_source = backend_source or (lambda: "gpu")
        # When set (by BubbleGroup, for mirroring), this PINS the bubble to a
        # specific screen, overriding the "bubble_screen" setting; the group
        # owns placement so it can light one bubble per monitor. Default None →
        # the setting drives placement (the standalone single-bubble path).
        self._screen_source = screen_source
        self._levels: deque[float] = deque([0.0] * BAR_COUNT, maxlen=BAR_COUNT)
        self._state = "idle"  # idle | recording | processing | final | error
        self._view = view  # minimal (one eliding line) | full (wrapped, grows)
        self._text = ""
        self._phase = 0.0  # drives the breathing wave while processing

        self._timer = QTimer(self)
        self._timer.setInterval(FPS_MS)
        self._timer.timeout.connect(self._tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._anim: QParallelAnimationGroup | None = None

    # ── states ──────────────────────────────────────────────────────────

    def start_recording(self) -> None:
        self._hide_timer.stop()
        self._levels.extend([0.0] * BAR_COUNT)
        self._set(state="recording", text="")
        self._timer.start()
        if self.isVisible():
            # Re-grabbed mid-fade-out: glide back instead of re-appearing.
            self._animate(opacity=1.0, pos=self._home_pos(), ms=160)
        else:
            self._fade_in()

    def set_partial(self, text: str) -> None:
        if self._state == "recording" and text:
            self._set(text=text)

    def start_processing(self) -> None:
        self._set(state="processing")

    def show_final(self, text: str) -> None:
        if self._state == "recording":
            return  # next take already started; the text landed regardless
        self._set(state="final", text=text)
        if not self.isVisible():
            # Re-show after the Wayland paste hid us to free keyboard focus
            # (see daemon._hide_bubble_for_paste). Opacity is untouched by a
            # bare hide(), so a plain show() restores the bubble at full alpha.
            self.show()
        self._hide_timer.start(1400)

    def show_error(self, msg: str) -> None:
        if self._state == "recording":
            return
        self._set(state="error", text=msg)
        if not self.isVisible():
            self.show()  # a Wayland paste error fires after the bubble-hide
        self._hide_timer.start(2500)

    def cancel(self) -> None:
        """Aborted take: freeze the waveform, flash 'Annulé', fade out.
        Forces dismissal from any state (unlike show_final/show_error, which
        defer to an ongoing recording — here the recording IS what we kill)."""
        self._timer.stop()
        self._set(state="cancelled", text="Annulé")
        self._hide_timer.start(800)

    def _set(self, state: str | None = None, text: str | None = None) -> None:
        if state is not None:
            self._state = state
        if text is not None:
            self._text = text
        self._apply_size()
        self.update()

    def set_view(self, view: str) -> None:
        self._view = view
        self._apply_size()
        self.update()

    # ── geometry ────────────────────────────────────────────────────────

    def _text_width(self) -> int:
        bars_end = 24 + BAR_COUNT * (BAR_W + BAR_GAP)
        return WIDTH - (bars_end + 14) - 24

    def _desired_height(self) -> int:
        if self._view != "full" or not self._text:
            return HEIGHT
        needed = (
            QFontMetrics(self.font())
            .boundingRect(
                QRect(0, 0, self._text_width(), 10_000),
                Qt.TextWordWrap,
                self._text,
            )
            .height()
        )
        return max(HEIGHT, min(MAX_HEIGHT, needed + 2 * V_PAD))

    def _apply_size(self) -> None:
        """Grow/shrink (full view), staying anchored above the screen bottom."""
        h = self._desired_height()
        if h != self.height():
            self.setFixedSize(WIDTH, h)
            if self.isVisible():
                self.move(self._home_pos())

    # ── animation plumbing ──────────────────────────────────────────────

    def _tick(self) -> None:
        if self._state == "recording":
            self._levels.append(self._level_source())
        else:
            self._phase += 0.16
        self.update()

    def _target_screen(self):
        """Which monitor the bubble lives on. When pinned by a BubbleGroup
        (`screen_source`), that wins; otherwise the "bubble_screen" setting
        resolves it (pin / cursor / focus / primary). Read fresh so a Réglages
        change lands on the next appearance."""
        if self._screen_source is not None:
            return self._screen_source() or QApplication.primaryScreen()
        return resolve_screen(settings.get("bubble_screen"))

    def _home_pos(self) -> QPoint:
        screen = self._target_screen()
        geo = screen.availableGeometry()
        return QPoint(
            geo.center().x() - WIDTH // 2,
            geo.bottom() - self.height() - MARGIN_BOTTOM,
        )

    def _fade_in(self) -> None:
        home = self._home_pos()
        self.move(home + QPoint(0, 12))
        self.setWindowOpacity(0.0)
        self.show()
        self._make_sticky()
        self._animate(opacity=1.0, pos=home, ms=160)

    def _make_sticky(self) -> None:
        """Pin to all virtual desktops: a mid-take workspace switch must not
        strand the bubble. Fire-and-forget — cosmetic, never blocks.

        xprop talks the X11 protocol; under native Wayland the compositor owns
        placement and stickiness, so this would be a silent no-op anyway —
        skip it explicitly (the launcher prefers XWayland, see daemon.run)."""
        if QApplication.platformName() != "xcb":
            return
        subprocess.Popen(
            [
                "xprop",
                "-id",
                str(int(self.winId())),
                "-f",
                "_NET_WM_DESKTOP",
                "32c",
                "-set",
                "_NET_WM_DESKTOP",
                "0xFFFFFFFF",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _fade_out(self) -> None:
        self._animate(
            opacity=0.0, pos=self.pos() + QPoint(0, 12), ms=280, then=self._sleep
        )

    def _sleep(self) -> None:
        if self._state == "recording":
            return  # a new take grabbed the bubble mid-fade
        self._timer.stop()
        self.hide()
        self._set(state="idle", text="")

    def _animate(
        self, opacity: float, pos: QPoint, ms: int, then: Callable | None = None
    ) -> None:
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setEndValue(opacity)
        slide = QPropertyAnimation(self, b"pos")
        slide.setEndValue(pos)
        for anim in (fade, slide):
            anim.setDuration(ms)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(anim)
        if then:
            group.finished.connect(then)
        self._anim = group  # keep alive; replacing drops the previous one
        group.start()

    # ── painting ────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(_BG)
        p.drawRoundedRect(QRectF(self.rect()), HEIGHT / 2, HEIGHT / 2)
        self._paint_bars(p)
        self._paint_text(p)
        p.end()

    def _engine_color(self) -> QColor:
        """green=GPU, blue=CPU — ambient indicator of the live backend."""
        return _GPU if self._backend_source() == "gpu" else _CPU

    def _bar_color(self) -> QColor:
        """The bar colour for the current state. Every state but error keeps the
        live backend hue: idle/recording/processing use it as-is, the final
        "landed" flash brightens it toward white (brighter, not a different
        colour — so green never means anything but GPU). Error is red."""
        if self._state == "error":
            return _ERR
        if self._state == "final":
            return _brighten(self._engine_color())
        return self._engine_color()

    def _paint_bars(self, p: QPainter) -> None:
        color = self._bar_color()
        if self._state != "recording":
            color = QColor(color)
            color.setAlpha(140)
        p.setBrush(color)

        x = 24.0
        cy = self.height() / 2
        max_half = (HEIGHT - 22) / 2
        for i in range(BAR_COUNT):
            if self._state == "recording":
                lvl = self._levels[i]
            elif self._state == "processing":
                # A bright pulse sweeping across the bars: clearly "scanning",
                # distinct from idle's breathing and final's green flash. Most
                # visible on long takes (the batched final decode ≈ 1 s).
                center = (self._phase * 0.8) % BAR_COUNT
                d = min(abs(i - center), BAR_COUNT - abs(i - center))  # wrap-around
                lvl = 0.15 + 0.6 * math.exp(-(d * d) / 4.0)
            else:  # idle / final / error: gentle breathing wave
                lvl = 0.18 + 0.14 * math.sin(self._phase + i * 0.45)
            half = 1.5 + max(0.0, lvl) * max_half
            p.drawRoundedRect(QRectF(x, cy - half, BAR_W, half * 2), 1.5, 1.5)
            x += BAR_W + BAR_GAP

    def _paint_text(self, p: QPainter) -> None:
        text = self._text or (_PLACEHOLDER if self._state == "recording" else "…")
        color = {
            "recording": _TEXT_LIVE if self._text else _TEXT_DIM,
            "processing": _TEXT_DIM,
            "final": _TEXT_LIVE,
            "error": _ERR,
        }.get(self._state, _TEXT_DIM)

        bars_end = 24 + BAR_COUNT * (BAR_W + BAR_GAP)
        p.setPen(color)

        # Full view (once text actually wraps): the whole take, top-aligned.
        # Overflow past MAX_HEIGHT trims oldest words behind an ellipsis.
        if self._view == "full" and self.height() > HEIGHT:
            rect = self.rect().adjusted(bars_end + 14, V_PAD, -24, -V_PAD)
            p.drawText(
                rect,
                Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
                self._trim_to_fit(text, rect),
            )
            return

        rect = self.rect().adjusted(bars_end + 14, 0, -24, 0)
        # Live speech: elide left so the freshest words stay visible.
        # Final flash: elide right — it reads as "this is what landed".
        mode = Qt.ElideRight if self._state == "final" else Qt.ElideLeft
        elided = QFontMetrics(self.font()).elidedText(text, mode, rect.width())
        p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

    def _trim_to_fit(self, text: str, rect) -> str:
        """Oldest words behind an ellipsis so the tail fits the rect.

        Called from paintEvent (30 fps while the waveform animates), so it
        must be O(1) on repaint: the result is cached per (text, rect) and
        recomputed — by bisection, not word-by-word — only when a new
        partial lands or the bubble resizes.
        """
        key = (text, rect.width(), rect.height())
        if self._trim_key != key:
            self._trim_key = key
            self._trim_result = self._trim_compute(text, rect)
        return self._trim_result

    def _trim_compute(self, text: str, rect) -> str:
        fm = QFontMetrics(self.font())

        def fits(t: str) -> bool:
            return fm.boundingRect(rect, Qt.TextWordWrap, t).height() <= rect.height()

        if fits(text):
            return text
        words = text.split(" ")
        lo, hi = 1, len(words) - 1  # smallest cut whose tail fits
        while lo < hi:
            mid = (lo + hi) // 2
            if fits("…" + " ".join(words[mid:])):
                hi = mid
            else:
                lo = mid + 1
        return "…" + " ".join(words[lo:])


class QueueChips(QWidget):
    """A small row of pills above the main bubble — one per take still in the
    decode queue (#15).

    The queue (#14) lets takes overlap: the main bubble shows the take you're
    speaking now, while earlier takes finish decoding behind it. These chips make
    that backlog visible — how many are still cooking — and flash each one as it
    lands (a brighter pulse of the backend hue, then it fades). Cosmetic and
    opt-out (`queue_chips`): the queue behaves identically with the strip hidden.

    Never takes focus (it sits over the user's window like the bubble). All
    methods assume the GUI thread — the daemon wires `queued`/`delivered` through
    queued signal connections, same as the bubble."""

    def __init__(
        self,
        backend_source: Callable[[], str] | None = None,
        screen_source: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._backend_source = backend_source or (lambda: "gpu")
        self._screen_source = screen_source
        # Ordered [seq, state] pairs; state is "decoding" | "delivered". A list
        # of lists (not a dict) so paint order matches arrival order, oldest left.
        self._chips: list[list] = []
        self._phase = 0.0  # drives the gentle breathing of decoding chips
        self._timer = QTimer(self)
        self._timer.setInterval(FPS_MS)
        self._timer.timeout.connect(self._tick)

    # ── model (pure-ish, headless-testable) ─────────────────────────────────

    def on_queued(self, seq: int) -> None:
        """A take entered the decode queue: add a decoding chip, show the strip."""
        if not settings.get("queue_chips"):
            return
        if any(c[0] == seq for c in self._chips):
            return  # idempotent — a duplicate signal must not double-add
        self._chips.append([seq, "decoding"])
        self._reflow()
        if not self.isVisible():
            self.show()
            self._make_sticky()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def on_delivered(self, seq: int) -> None:
        """That take landed: flash the chip, then drop it after a short beat."""
        for chip in self._chips:
            if chip[0] == seq:
                chip[1] = "delivered"
                QTimer.singleShot(700, lambda s=seq: self._remove(s))
                break
        self.update()

    def _remove(self, seq: int) -> None:
        self._chips = [c for c in self._chips if c[0] != seq]
        if not self._chips:
            self._timer.stop()
            self.hide()
        else:
            self._reflow()
        self.update()

    # ── geometry / placement ────────────────────────────────────────────────

    def _content_width(self) -> int:
        n = max(1, len(self._chips))
        return CHIP_PAD * 2 + n * CHIP_D + (n - 1) * CHIP_GAP

    def _target_screen(self):
        if self._screen_source is not None:
            return self._screen_source() or QApplication.primaryScreen()
        return resolve_screen(settings.get("bubble_screen"))

    def _reflow(self) -> None:
        """Resize to the chip count and re-anchor just above the main bubble,
        bottom-centred on the same screen."""
        w = self._content_width()
        self.setFixedSize(w, CHIP_H)
        screen = self._target_screen()
        geo = screen.availableGeometry()
        x = geo.center().x() - w // 2
        y = geo.bottom() - MARGIN_BOTTOM - HEIGHT - CHIP_GAP_ABOVE - CHIP_H
        self.move(QPoint(x, y))

    def _make_sticky(self) -> None:
        # Pin to all desktops like the bubble; X11 only (Wayland compositor owns
        # placement). Fire-and-forget cosmetic.
        if QApplication.platformName() != "xcb":
            return
        subprocess.Popen(
            [
                "xprop",
                "-id",
                str(int(self.winId())),
                "-f",
                "_NET_WM_DESKTOP",
                "32c",
                "-set",
                "_NET_WM_DESKTOP",
                "0xFFFFFFFF",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ── paint ────────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._phase += 0.16
        self.update()

    def _engine_color(self) -> QColor:
        return _GPU if self._backend_source() == "gpu" else _CPU

    def paintEvent(self, event) -> None:
        if not self._chips:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(_BG)
        p.drawRoundedRect(QRectF(self.rect()), CHIP_H / 2, CHIP_H / 2)
        base = self._engine_color()
        cy = self.height() / 2
        x = float(CHIP_PAD)
        for _seq, state in self._chips:
            color = QColor(chip_color(state, base))
            if state == "decoding":
                # Gentle breathing so "still working" reads as alive, not stalled.
                color.setAlpha(round(150 + 80 * (0.5 + 0.5 * math.sin(self._phase))))
            p.setBrush(color)
            p.drawEllipse(QRectF(x, cy - CHIP_D / 2, CHIP_D, CHIP_D))
            x += CHIP_D + CHIP_GAP
        p.end()


class BubbleGroup(QObject):
    """The daemon's face when it may span several monitors.

    Holds one `Bubble` per screen (created lazily, reused across takes) and fans
    every call out to the bubbles that are *active for the current take*. The
    active set is resolved fresh at each take start from "bubble_screen"
    (`resolve_screens`), so BOTH the chosen monitor and mirror mode apply live —
    no restart, matching the rest of Réglages.

    "all" lights every screen (a true mirror); every other mode lights exactly
    one. A one-screen take is therefore the very same single Bubble as before,
    just reached through the group — single-monitor users pay nothing.

    Exposes the same surface the daemon wires to a Bubble (start_recording,
    set_partial, start_processing, show_final, show_error, cancel, set_view) plus
    a `@Slot hide()` so the Wayland paste-hide
    (`daemon._hide_bubble_for_paste`'s BlockingQueuedConnection invoke) yields
    keyboard focus on EVERY mirror, not just one — else the paste lands in
    whichever bubble still holds focus instead of the user's window."""

    def __init__(
        self,
        level_source: Callable[[], float],
        view: str = "minimal",
        backend_source: Callable[[], str] | None = None,
    ) -> None:
        super().__init__()
        self._level_source = level_source
        self._view = view
        self._backend_source = backend_source
        self._pool: dict[str, Bubble] = {}  # by QScreen.name(), reused
        self._active: list[Bubble] = []  # lit for the current take
        # The queue-chip strip (#15), created lazily on the first queued take so
        # single-take users never instantiate it. One strip, on the resolved
        # bubble screen — a queue indicator, not per-monitor content.
        self._chips: QueueChips | None = None

    def _bubble_for(self, screen) -> Bubble:
        """The pooled Bubble pinned to `screen`, created on first use. The pin
        re-resolves by NAME each appearance, so an unplugged monitor degrades to
        primary instead of dangling a freed QScreen pointer."""
        name = screen.name()
        bubble = self._pool.get(name)
        if bubble is None:
            bubble = Bubble(
                self._level_source,
                view=self._view,
                backend_source=self._backend_source,
                screen_source=lambda: _screen_by_name(name),
            )
            self._pool[name] = bubble
        return bubble

    def _activate(self) -> list[Bubble]:
        """Resolve the take's active set, hiding any bubble that was lit last
        take but isn't now (mode change, mouse moved screen, monitor unplugged).
        De-dupes by screen name so a mode can't light the same monitor twice."""
        by_name = {s.name(): s for s in resolve_screens(settings.get("bubble_screen"))}
        new_active = [self._bubble_for(s) for s in by_name.values()]
        for bubble in self._active:
            if bubble not in new_active:
                bubble.hide()
        self._active = new_active
        return new_active

    # ── fan-out (mirrors Bubble's public surface) ───────────────────────────

    def start_recording(self) -> None:
        for bubble in self._activate():
            bubble.start_recording()

    def set_partial(self, text: str) -> None:
        for bubble in self._active:
            bubble.set_partial(text)

    def start_processing(self) -> None:
        for bubble in self._active:
            bubble.start_processing()

    def show_final(self, text: str) -> None:
        for bubble in self._active:
            bubble.show_final(text)

    def show_error(self, msg: str) -> None:
        for bubble in self._active:
            bubble.show_error(msg)

    def cancel(self) -> None:
        for bubble in self._active:
            bubble.cancel()

    def set_view(self, view: str) -> None:
        # Apply to every pooled bubble AND remember it, so a screen first lit on
        # a later take is born with the current view.
        self._view = view
        for bubble in self._pool.values():
            bubble.set_view(view)

    @Slot()
    def hide(self) -> None:
        for bubble in self._active:
            bubble.hide()

    # ── queue chips (#15) ────────────────────────────────────────────────────

    def _chip_strip(self) -> "QueueChips":
        if self._chips is None:
            self._chips = QueueChips(
                backend_source=self._backend_source,
                screen_source=lambda: resolve_screen(settings.get("bubble_screen")),
            )
        return self._chips

    @Slot(int)
    def on_queued(self, seq: int) -> None:
        self._chip_strip().on_queued(seq)

    @Slot(int)
    def on_delivered(self, seq: int) -> None:
        if self._chips is not None:
            self._chips.on_delivered(seq)
