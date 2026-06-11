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
from collections import deque
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QWidget

WIDTH, HEIGHT = 460, 56
MARGIN_BOTTOM = 64  # gap between bubble and screen bottom
BAR_COUNT, BAR_W, BAR_GAP = 18, 3, 3
FPS_MS = 33  # one repaint per Recorder level sample

_BG = QColor(17, 19, 27, 236)
_TEXT_LIVE = QColor(205, 214, 244)
_TEXT_DIM = QColor(127, 132, 156)
_ACCENT = QColor(122, 162, 247)  # recording bars
_OK = QColor(158, 206, 106)  # final-flash bars
_ERR = QColor(247, 118, 142)

_PLACEHOLDER = "Je t'écoute…"


class Bubble(QWidget):
    def __init__(self, level_source: Callable[[], float]) -> None:
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
        font = self.font()
        font.setPointSizeF(10.5)
        self.setFont(font)

        self._level_source = level_source
        self._levels: deque[float] = deque([0.0] * BAR_COUNT, maxlen=BAR_COUNT)
        self._state = "idle"  # idle | recording | processing | final | error
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
        self._hide_timer.start(1400)

    def show_error(self, msg: str) -> None:
        if self._state == "recording":
            return
        self._set(state="error", text=msg)
        self._hide_timer.start(2500)

    def _set(self, state: str | None = None, text: str | None = None) -> None:
        if state is not None:
            self._state = state
        if text is not None:
            self._text = text
        self.update()

    # ── animation plumbing ──────────────────────────────────────────────

    def _tick(self) -> None:
        if self._state == "recording":
            self._levels.append(self._level_source())
        else:
            self._phase += 0.16
        self.update()

    def _home_pos(self) -> QPoint:
        screen = QApplication.primaryScreen().availableGeometry()
        return QPoint(
            screen.center().x() - WIDTH // 2,
            screen.bottom() - HEIGHT - MARGIN_BOTTOM,
        )

    def _fade_in(self) -> None:
        home = self._home_pos()
        self.move(home + QPoint(0, 12))
        self.setWindowOpacity(0.0)
        self.show()
        self._animate(opacity=1.0, pos=home, ms=160)

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

    def _paint_bars(self, p: QPainter) -> None:
        color = {"final": _OK, "error": _ERR}.get(self._state, _ACCENT)
        if self._state != "recording":
            color = QColor(color)
            color.setAlpha(140)
        p.setBrush(color)

        x = 24.0
        cy = HEIGHT / 2
        max_half = (HEIGHT - 22) / 2
        for i in range(BAR_COUNT):
            if self._state == "recording":
                lvl = self._levels[i]
            else:  # gentle breathing wave while the GPU thinks / flashes
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
        rect = self.rect().adjusted(bars_end + 14, 0, -24, 0)
        # Live speech: elide left so the freshest words stay visible.
        # Final flash: elide right — it reads as "this is what landed".
        mode = Qt.ElideRight if self._state == "final" else Qt.ElideLeft
        elided = QFontMetrics(self.font()).elidedText(text, mode, rect.width())
        p.setPen(color)
        p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
