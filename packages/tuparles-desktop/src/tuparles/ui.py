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
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

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
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from tuparles import settings

WIDTH, HEIGHT = 460, 56  # the pill; also the ribbon's min width + 1-line height
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
# Amber: a lost final whose partial we salvaged (#27). Warmer than error red —
# "held, not failed" — so a recovery never reads as the hard red flip of a crash.
_AMBER = QColor(250, 179, 135)

# Once a decode runs longer than this, the bubble shows an elapsed counter so a
# slow CPU take reads as "working (12s)", not "frozen?" (#28).
DECODE_COUNTER_AFTER_S = 3.0

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


def decode_counter_text(elapsed_s: float) -> str:
    """The elapsed-counter badge for a slow decode (#28): "" until the take has
    run past DECODE_COUNTER_AFTER_S, then "(Ns)" so a long CPU decode reads as
    working, not frozen. Pure — headless-tested, no paint pass needed."""
    if elapsed_s < DECODE_COUNTER_AFTER_S:
        return ""
    return f"({int(elapsed_s)}s)"


def chip_color(state: str, base: QColor) -> QColor:
    """A queue chip's colour: the live backend hue while decoding, brightened
    toward white the moment it's delivered (same hue, brighter — so green never
    stops meaning GPU). Any unknown state reads as still-decoding."""
    return _brighten(base, 0.5) if state == "delivered" else base


# ── the ribbon (#132): the "full" view grows WIDE first ──────────────────────
# The old full view was a 460×300 vertical tower planted over the code. The
# ribbon spends the abundant axis instead: it widens along the bottom edge up to
# a fraction of the screen BEFORE it ever adds a second line, then caps at
# `bubble_lines` (default 2, ≈76 px). Older text drops into a dim, smaller,
# left-aligned "history" register above the bright, larger, RIGHT-anchored live
# tail — so recency reads as brightness + size (never a hue change, house
# doctrine `feedback-signal-more-by-brightness-not-hue`) and the freshest words
# sit at a fixed glance point (the end of the bright line), exactly where the
# old ElideLeft trained the eye. The beginning of the take stays visible up to
# RIBBON_MAX_CHARS; only past that are the oldest words trimmed behind a "…".
#
# Every layout DECISION is a pure function here (measurement is injected as a
# `measure(str)->px` callable), so the growth stages, the register split and the
# char budget are tested headless with a fake measurer — the paint pass only
# draws what these return (the house pattern, like `chip_color`/`state_color`).

RIBBON_MAX_CHARS = 750  # chars kept visible before the oldest trim behind "…"
RIBBON_HIST_SCALE = 0.78  # history register font vs the live tail (recency=size)


@dataclass(frozen=True)
class RibbonLayout:
    """The decided ribbon geometry+content for one text, screen and setting set.

    `width` is the widget width (wide-first growth, capped at the ceiling).
    `single_line` is True when the whole text sits on one line (it grew to fit,
    or a 1-line ceiling forces an elide); then `live` is the whole text and
    `history` is "". Otherwise `live` is the right-anchored freshest tail and
    `history` is the older leading remainder for the compressed register."""

    width: int
    live: str
    history: str
    single_line: bool


def ribbon_ceiling_width(screen_w: int, frac: float, fixed_w: int) -> int:
    """The ribbon's width ceiling: `frac`>0 → that fraction of the screen (never
    below the fixed pill width); `frac`<=0 → the fixed pill width itself, the
    total-override back to the 460 px footprint for people who liked it."""
    if frac <= 0:
        return fixed_w
    return max(fixed_w, round(screen_w * frac))


def ribbon_widen(content_px: int, fixed_w: int, ceiling_w: int) -> int:
    """Wide-first growth: the widget widens with its content, from the fixed pill
    width up to the ceiling. Clamped both ends so a one-word take stays a pill
    and a monologue never exceeds the screen fraction."""
    return max(fixed_w, min(ceiling_w, content_px))


def ribbon_budget(text: str, max_chars: int = RIBBON_MAX_CHARS) -> str:
    """Char budget: keep the beginning intact up to `max_chars`; past that, drop
    the OLDEST characters behind a leading "…" (the tail is what you're saying
    now). A no-op under budget, so the whole take shows until it's genuinely
    long."""
    if len(text) <= max_chars:
        return text
    return "…" + text[-(max_chars - 1) :]


def fit_trailing_words(words: list[str], measure: Callable[[str], int], avail_px: int):
    """The register split core: the longest SUFFIX of `words` whose joined string
    fits `avail_px` (by the injected measurer). Returns (start_index, tail) —
    `words[start_index:]` is the live line, `words[:start_index]` the history.
    Bisection (monotone: a shorter tail fits whenever a longer one does), so it's
    O(log n) measures per frame, not O(n)."""
    if not words:
        return 0, ""
    lo, hi = 0, len(words)  # smallest start whose tail fits (empty tail always fits)
    while lo < hi:
        mid = (lo + hi) // 2
        if measure(" ".join(words[mid:])) <= avail_px:
            hi = mid
        else:
            lo = mid + 1
    # Never hand back an empty live line when even one word overflows: keep the
    # last word (it will elide in paint) so the tail is never blank.
    start = min(lo, len(words) - 1)
    return start, " ".join(words[start:])


def plan_ribbon(
    text: str,
    *,
    measure_live: Callable[[str], int],
    measure_hist: Callable[[str], int],
    screen_w: int,
    max_frac: float,
    fixed_w: int,
    chrome_px: int,
    max_lines: int,
    max_chars: int = RIBBON_MAX_CHARS,
) -> RibbonLayout:
    """Decide the ribbon layout for `text`. Pure: `measure_live`/`measure_hist`
    are `str->px` (QFontMetrics.horizontalAdvance in production, a fake in tests).
    `chrome_px` is the non-text width (bars + paddings). `max_lines` (1..3) caps
    height; 1 = a single strip, no history register."""
    text = text or ""
    ceiling = ribbon_ceiling_width(screen_w, max_frac, fixed_w)
    single_px = measure_live(text)
    width = ribbon_widen(chrome_px + single_px, fixed_w, ceiling)
    avail_live = width - chrome_px
    if single_px <= avail_live or max_lines <= 1:
        # Fits by widening, or the user pinned a single strip: one line. When a
        # forced single strip overflows, paint elides-left (freshest visible).
        return RibbonLayout(width=width, live=text, history="", single_line=True)
    # Two+ registers, at the ceiling width. Budget first (drop oldest past the
    # cap), then peel the freshest tail onto the bright line; the rest is history.
    width = ceiling
    avail_live = width - chrome_px
    words = ribbon_budget(text, max_chars).split(" ")
    start, live = fit_trailing_words(words, measure_live, avail_live)
    history = " ".join(words[:start])
    return RibbonLayout(width=width, live=live, history=history, single_line=False)


class Bubble(QWidget):
    def __init__(
        self,
        level_source: Callable[[], float],
        view: str = "minimal",
        backend_source: Callable[[], str] | None = None,
        screen_source: Callable[[], object] | None = None,
        clock: Callable[[], float] | None = None,
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
        self._layout_key: tuple | None = None  # _ribbon_layout memo
        self._layout: RibbonLayout | None = None
        self._apply_font()  # point size from « Taille du texte » (#132)

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
        # idle | recording | processing | final | error | recovered | cancelled
        self._state = "idle"
        self._view = view  # minimal (one eliding line) | full (wrapped, grows)
        self._text = ""
        self._phase = 0.0  # drives the breathing wave while processing
        # Wall clock (injectable for tests). _processing_since stamps when the
        # current decode began, so a long take can show an elapsed counter (#28).
        self._clock = clock or time.monotonic
        self._processing_since: float | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(FPS_MS)
        self._timer.timeout.connect(self._tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_hide_timeout)
        # One-slot pending status toast (#132). A persistent-state notice (e.g.
        # the GPU→CPU fallback) that arrives while a take is live can't show now,
        # so it waits here (latest wins) and re-fires the next time the bubble
        # would go idle — a dropped state signal is a signal forgotten.
        self._pending_status: str | None = None

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
        self._processing_since = self._clock()
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

    def show_recovered(self, partial: str) -> None:
        """Never recant (#27): the final decode was lost but a partial was
        visibly painted — keep those words on screen, dimmed and tinted amber
        with a 'Ctrl+V' hint (the partial was copied), and dwell a beat longer.
        A salvage reads as 'held for you', not the hard red flip of a failure.
        Defers to a live recording, like show_final/show_error — the clipboard
        copy already happened on the worker; this is only the face of it."""
        if self._state == "recording":
            return
        self._set(state="recovered", text=partial)
        if not self.isVisible():
            self.show()
        self._hide_timer.start(2800)

    def show_status(self, msg: str) -> None:
        """A persistent-STATE notice (the GPU→CPU fallback, #27/#132), distinct
        from a per-take transcript flash: a transcript that lands mid-next-take
        is rightly dropped (the text went into your window regardless), but a
        state that changed must never be lost to a well-timed glance.

        So this NEVER silently drops. While a take is live it can't show, so it
        QUEUES (one slot, latest wins) and re-fires the moment the bubble next
        goes idle (`_on_hide_timeout`). Idle already → show it now. This closes
        the "state assigned a transient channel, and the channel has a drop path"
        class the project already learned for data ('record misses harder')."""
        if self._state == "recording":
            self._pending_status = msg
            return
        self._set(state="final", text=msg)
        if not self.isVisible():
            self.show()
        self._hide_timer.start(1400)

    def cancel(self) -> None:
        """Aborted take: freeze the waveform, flash 'Annulé', fade out.
        Forces dismissal from any state (unlike show_final/show_error, which
        defer to an ongoing recording — here the recording IS what we kill)."""
        self._timer.stop()
        self._set(state="cancelled", text="Annulé")
        self._hide_timer.start(800)

    def _set(self, state: str | None = None, text: str | None = None) -> None:
        if state is not None:
            if state != "processing":
                self._processing_since = None  # counter only runs during a decode
            self._state = state
        if text is not None:
            self._text = text
        self._apply_font()
        self._apply_size()
        self.update()

    def set_view(self, view: str) -> None:
        self._view = view
        self._apply_font()
        self._apply_size()
        self.update()

    # ── geometry ────────────────────────────────────────────────────────

    def _font_pt(self) -> float:
        """« Taille du texte » (#132): the live tail's point size, the missing
        accessibility + HiDPI knob. Default 10.5 (the historical size)."""
        try:
            return float(settings.get("bubble_font_pt") or 10.5)
        except (TypeError, ValueError):
            return 10.5

    def _apply_font(self) -> None:
        """Sync the widget font to « Taille du texte » so a Réglages change lands
        on the next take (no restart) and every measurement below sees it."""
        pt = self._font_pt()
        if abs(self.font().pointSizeF() - pt) > 0.01:
            f = self.font()
            f.setPointSizeF(pt)
            self.setFont(f)

    def _hist_font(self) -> QFont:
        """The compressed-register font: smaller than the live tail so recency
        reads as SIZE (with brightness), never a hue change (house doctrine)."""
        f = QFont(self.font())
        f.setPointSizeF(max(6.0, self.font().pointSizeF() * RIBBON_HIST_SCALE))
        return f

    def _chrome_px(self) -> int:
        """Non-text width: the bars, the gap after them (14), the right pad (24).
        The ribbon's text area is the widget width minus this."""
        bars_end = 24 + BAR_COUNT * (BAR_W + BAR_GAP)
        return bars_end + 14 + 24

    def _max_frac(self) -> float:
        """« Largeur du bandeau » — the screen fraction the ribbon may fill.
        0 = the fixed 460 px pill (total override)."""
        try:
            return float(settings.get("bubble_max_width"))
        except (TypeError, ValueError):
            return 0.92

    def _max_lines(self) -> int:
        """« Lignes du bandeau » (1..3): the ribbon's line cap. 1 = a single
        strip, no history register."""
        try:
            n = int(settings.get("bubble_lines"))
        except (TypeError, ValueError):
            return 2
        return max(1, min(3, n))

    def _ribbon_layout(self) -> RibbonLayout:
        """Decide + memoize the ribbon layout for the current text/screen/
        settings — O(1) per repaint (recomputed only when an input changes),
        like `_trim_to_fit`. The pure `plan_ribbon` does the deciding; here we
        just wire QFontMetrics as the measurer."""
        screen = self._target_screen()
        screen_w = screen.availableGeometry().width()
        frac = self._max_frac()
        max_lines = self._max_lines()
        pt = self.font().pointSizeF()
        key = (self._text, screen_w, frac, max_lines, pt)
        if self._layout_key != key or self._layout is None:
            live_fm = QFontMetrics(self.font())
            hist_fm = QFontMetrics(self._hist_font())
            self._layout_key = key
            self._layout = plan_ribbon(
                self._text,
                measure_live=live_fm.horizontalAdvance,
                measure_hist=hist_fm.horizontalAdvance,
                screen_w=screen_w,
                max_frac=frac,
                fixed_w=WIDTH,
                chrome_px=self._chrome_px(),
                max_lines=max_lines,
            )
        return self._layout

    def _hist_line_h(self) -> int:
        return QFontMetrics(self._hist_font()).height() + 4

    def _history_lines(self, layout: RibbonLayout) -> int:
        """How many compressed lines the history wraps to: ≥1 when there's
        history, capped at `bubble_lines`-1 (the live tail owns the last line)."""
        if not layout.history:
            return 0
        cap = max(1, self._max_lines() - 1)
        avail = max(1, layout.width - self._chrome_px())
        fm = QFontMetrics(self._hist_font())
        needed = fm.boundingRect(
            QRect(0, 0, avail, 10_000), Qt.TextWordWrap, layout.history
        ).height()
        line_h = max(1, fm.lineSpacing())
        return max(1, min(cap, math.ceil(needed / line_h)))

    def _desired_size(self) -> tuple[int, int]:
        """(width, height) for the current view. Minimal (and empty full) → the
        fixed pill. A non-empty full view is the ribbon: wide-first width, and
        height of one line (HEIGHT) until the tail overflows, then +1 line per
        used history line up to « Lignes du bandeau »."""
        if self._view != "full" or not self._text:
            return WIDTH, HEIGHT
        layout = self._ribbon_layout()
        if layout.single_line:
            return layout.width, HEIGHT
        return layout.width, HEIGHT + self._history_lines(layout) * self._hist_line_h()

    def _apply_size(self) -> None:
        """Resize the ribbon (full view) in BOTH axes, re-centred above the
        screen bottom on every change — width now varies too (#132), so a widen
        must re-anchor x, not only y."""
        w, h = self._desired_size()
        if (w, h) != (self.width(), self.height()):
            self.setFixedSize(w, h)
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
            geo.center().x() - self.width() // 2,  # width now varies (ribbon, #132)
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

    def _on_hide_timeout(self) -> None:
        """A shown toast's dwell elapsed. If a status notice is pending and we're
        no longer recording, show it now — still visible, full opacity, no fade
        gymnastics — instead of fading (#132). Consume it first so its own
        subsequent timeout fades normally rather than looping."""
        if self._pending_status is not None and self._state != "recording":
            msg, self._pending_status = self._pending_status, None
            self.show_status(msg)
            return
        self._fade_out()

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
        """The bar colour for the current state. Every state but error/recovered
        keeps the live backend hue: idle/recording/processing use it as-is, the
        final "landed" flash brightens it toward white (brighter, not a different
        colour — so green never means anything but GPU). Error is red; a recovered
        partial is amber (held, not failed)."""
        if self._state == "error":
            return _ERR
        if self._state == "recovered":
            return _AMBER
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

    def _badge(self) -> tuple[str, QColor] | None:
        """A small right-aligned tag for the minimal pill: an amber 'Ctrl+V' hint
        on a recovered partial (#27), or a dim '(Ns)' elapsed counter once a
        decode runs long (#28). None when neither applies."""
        if self._state == "recovered":
            return ("Ctrl+V", _AMBER)
        if self._state == "processing" and self._processing_since is not None:
            txt = decode_counter_text(self._clock() - self._processing_since)
            if txt:
                return (txt, _TEXT_DIM)
        return None

    def _paint_text(self, p: QPainter) -> None:
        text = self._text or (_PLACEHOLDER if self._state == "recording" else "…")
        color = {
            "recording": _TEXT_LIVE if self._text else _TEXT_DIM,
            "processing": _TEXT_DIM,
            "final": _TEXT_LIVE,
            "error": _ERR,
            "recovered": _TEXT_DIM,
        }.get(self._state, _TEXT_DIM)

        bars_end = 24 + BAR_COUNT * (BAR_W + BAR_GAP)
        p.setPen(color)

        # Full view, once the tail no longer fits one (widened) line: the ribbon's
        # two registers (#132). A single-line full view falls through to the
        # elide path below — it's just a pill that grew wide to fit.
        if self._view == "full" and self._text:
            layout = self._ribbon_layout()
            if not layout.single_line:
                self._paint_ribbon(p, layout, color, bars_end)
                return

        rect = self.rect().adjusted(bars_end + 14, 0, -24, 0)
        fm = QFontMetrics(self.font())
        # Right-aligned badge ('Ctrl+V' / '(Ns)'): paint it first and reserve its
        # width so the main text elides clear of it instead of overlapping.
        badge = self._badge()
        if badge is not None:
            btext, bcolor = badge
            bw = fm.horizontalAdvance(btext)
            p.setPen(bcolor)
            p.drawText(rect, Qt.AlignVCenter | Qt.AlignRight, btext)
            p.setPen(color)
            rect = rect.adjusted(0, 0, -(bw + 10), 0)
        # Live speech: elide left so the freshest words stay visible.
        # Final flash: elide right — it reads as "this is what landed".
        mode = Qt.ElideRight if self._state == "final" else Qt.ElideLeft
        elided = fm.elidedText(text, mode, rect.width())
        p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

    def _paint_ribbon(
        self, p: QPainter, layout: RibbonLayout, live_color: QColor, bars_end: int
    ) -> None:
        """Two registers (#132): a dim, smaller, left-aligned history above a
        bright, larger, RIGHT-anchored live tail. Recency = brightness + size;
        the freshest words sit at a fixed glance point (the end of the bright
        line), and the beginning of the take stays visible in the history."""
        left = bars_end + 14
        avail = self.width() - 24 - left
        live_font = self.font()
        hist_font = self._hist_font()
        live_fm = QFontMetrics(live_font)
        live_h = live_fm.height()
        # Live tail: the bottom line, live font + colour, right-anchored. It
        # already fits `avail` by construction; elide-left is a belt for the
        # one-tick 800-char-cap edge.
        live_rect = QRect(left, self.height() - V_PAD - live_h, avail, live_h)
        p.setFont(live_font)
        p.setPen(live_color)
        p.drawText(
            live_rect,
            Qt.AlignRight | Qt.AlignVCenter,
            live_fm.elidedText(layout.live, Qt.ElideLeft, avail),
        )
        # History: the older leading remainder, dim + smaller, left-aligned in
        # the space above the live line. Word-wrapped; oldest trimmed behind "…"
        # only if it overflows its lines (past the char budget on a small screen).
        if layout.history:
            hist_rect = QRect(left, V_PAD, avail, live_rect.top() - V_PAD)
            p.setFont(hist_font)
            p.setPen(_TEXT_DIM)
            p.drawText(
                hist_rect,
                Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
                self._trim_to_fit(layout.history, hist_rect, hist_font),
            )
        p.setFont(live_font)  # restore for anything painted after

    def _trim_to_fit(self, text: str, rect, font: QFont | None = None) -> str:
        """Oldest words behind an ellipsis so the text fits the rect at `font`
        (default the widget font — the history register passes its smaller one).

        Called from paintEvent (30 fps while the waveform animates), so it
        must be O(1) on repaint: the result is cached per (text, rect, size) and
        recomputed — by bisection, not word-by-word — only when a new
        partial lands or the bubble resizes.
        """
        font = font or self.font()
        key = (text, rect.width(), rect.height(), font.pointSizeF())
        if self._trim_key != key:
            self._trim_key = key
            self._trim_result = self._trim_compute(text, rect, font)
        return self._trim_result

    def _trim_compute(self, text: str, rect, font: QFont) -> str:
        fm = QFontMetrics(font)

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

    def show_recovered(self, partial: str) -> None:
        for bubble in self._active:
            bubble.show_recovered(partial)

    def show_status(self, msg: str) -> None:
        for bubble in self._active:
            bubble.show_status(msg)

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
