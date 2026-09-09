"""One stylesheet for TuParles' windows, in the bubble's own colours.

Qt6 is a 2026 toolkit, but an *unstyled* Qt6 app is a 1996 one. When no
platform theme plugin resolves — a GNOME box whose QT_QPA_PLATFORMTHEME points
at the Qt5 bridge resolves nothing for Qt6 — widgets fall back to bare Fusion:
square corners, hairline borders, chunky scrollbars, no spacing. So rather than
depend on the user's Qt configuration, which we do not control and which
differs on every box, our dialogs bring their own paint. Same reasoning as the
rest of the app: it has to look right on a laptop on the train.

The palette is the bubble's own (ui.py), so Réglages and the overlay read as
one product. Light and dark are both derived and chosen from the running
QPalette — a tool that only looks right on a dark desktop looks broken on half
of them.
"""

import os
import pathlib

_TICK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" '
    'viewBox="0 0 14 14"><path d="M2.6 7.4 L5.5 10.3 L11.4 3.9" fill="none" '
    'stroke="{color}" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)
_CHEVRON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="7" '
    'viewBox="0 0 12 7"><path d="{path}" fill="none" stroke="{color}" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
_CHEVRON_DOWN = "M1.4 1.4 L6 5.2 L10.6 1.4"
_CHEVRON_UP = "M1.4 5.2 L6 1.4 L10.6 5.2"


def _icon(kind: str, color: str, svg: str) -> str:
    """Path to a recoloured icon, written once into the cache dir.

    Qt needs these at all because a stylesheet-painted checkbox indicator
    draws no glyph of its own, and Qt's CSS-border arrow trick renders as a
    blob rather than a triangle. They live on disk because QSS `url()` is not
    a browser's: it resolves files and Qt resources only, and a `data:` URI
    loads nothing at all — silently, which is how it survives a code review.
    Named by kind+colour, so switching palette writes a new file instead of
    serving a stale one. Returns "" if the cache is unwritable; the caller
    then omits the image and the widget keeps its plain painted state.
    """
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    slug = "".join(ch for ch in color if ch.isalnum())
    try:
        directory = pathlib.Path(base) / "tuparles" / "icons"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{kind}-{slug}.svg"
        if not path.exists():
            path.write_text(svg, encoding="utf-8")
    except OSError:
        return ""
    return path.as_posix()


def _image(path: str) -> str:
    """An `image:` declaration, or nothing when the icon is unavailable."""
    return f"image: url({path});" if path else ""


# The bubble's palette (ui.py) promoted to named roles. Dark is the house look;
# light is the same hues at the other end so the accent still means "TuParles".
_DARK = {
    "window": "#11131b",  # ui._BG, opaque
    "card": "#181b26",
    "field": "#1e2230",
    "border": "#2f3446",
    "border_strong": "#3d4459",
    "text": "#cdd6f4",  # ui._TEXT_LIVE
    "subtext": "#8b90a6",  # ui._TEXT_DIM, lifted for prose contrast
    "accent": "#7ac782",  # ui._GPU — the house green
    "accent_soft": "rgba(122, 199, 130, 0.15)",
    "accent_text": "#11131b",
    "hover": "rgba(205, 214, 244, 0.07)",
}

_LIGHT = {
    "window": "#f4f5f8",
    "card": "#ffffff",
    "field": "#ffffff",
    "border": "#d8dbe3",
    "border_strong": "#b9bdc9",
    "text": "#1b1f2b",
    "subtext": "#5d6478",
    "accent": "#2f8f4a",  # the same green, darkened to stay readable on white
    "accent_soft": "rgba(47, 143, 74, 0.12)",
    "accent_text": "#ffffff",
    "hover": "rgba(27, 31, 43, 0.05)",
}


def is_dark(palette=None) -> bool:
    """Should we paint dark? Read from the running QPalette, defaulting to the
    house dark when there is no application to ask (headless renders)."""
    if palette is None:
        try:
            from PySide6.QtWidgets import QApplication

            # Static accessor, not the instance's: `instance()` is typed as
            # QCoreApplication, which knows nothing about palettes.
            palette = QApplication.palette() if QApplication.instance() else None
        except Exception:
            palette = None
    if palette is None:
        return True
    try:
        return palette.window().color().lightness() < 128
    except Exception:
        return True


def tokens(dark: bool | None = None) -> dict:
    """The colour roles for the chosen mode."""
    if dark is None:
        dark = is_dark()
    return dict(_DARK if dark else _LIGHT)


def stylesheet(dark: bool | None = None) -> str:
    """QSS for a TuParles dialog. Scoped by design: applied per-window, never
    app-wide, so it can never repaint the bubble or the ribbon — those draw
    themselves and would fight a stylesheet."""
    t = tokens(dark)
    tick = _icon("tick", t["accent_text"], _TICK_SVG.format(color=t["accent_text"]))
    chevron_down = _icon(
        "chevron-down",
        t["subtext"],
        _CHEVRON_SVG.format(path=_CHEVRON_DOWN, color=t["subtext"]),
    )
    chevron_up = _icon(
        "chevron-up",
        t["subtext"],
        _CHEVRON_SVG.format(path=_CHEVRON_UP, color=t["subtext"]),
    )
    return f"""
    QDialog {{
        background: {t["window"]};
        color: {t["text"]};
    }}
    QWidget#page, QWidget#sidebar {{
        background: transparent;
    }}
    QLabel {{
        color: {t["text"]};
        font-size: 10pt;
        background: transparent;
    }}
    QLabel#pageTitle {{
        font-size: 15pt;
        font-weight: 600;
        padding-bottom: 2px;
    }}
    QLabel#sectionTitle {{
        font-size: 10pt;
        font-weight: 600;
        color: {t["accent"]};
        padding-top: 8px;
    }}
    QLabel#hint {{
        color: {t["subtext"]};
        font-size: 9pt;
        padding-bottom: 4px;
    }}
    QLabel#fieldLabel {{
        color: {t["subtext"]};
        font-size: 9pt;
    }}

    /* Sidebar: the nav is a list that must not look like one. */
    QListWidget#nav {{
        background: {t["card"]};
        border: none;
        border-right: 1px solid {t["border"]};
        outline: none;
        padding: 10px 8px;
        font-size: 10pt;
    }}
    QListWidget#nav::item {{
        color: {t["subtext"]};
        padding: 9px 12px;
        border-radius: 8px;
        margin-bottom: 2px;
    }}
    QListWidget#nav::item:hover {{
        background: {t["hover"]};
        color: {t["text"]};
    }}
    QListWidget#nav::item:selected {{
        background: {t["accent_soft"]};
        color: {t["accent"]};
        font-weight: 600;
    }}

    /* Inputs */
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit {{
        background: {t["field"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 7px 10px;
        font-size: 10pt;
        selection-background-color: {t["accent"]};
        selection-color: {t["accent_text"]};
    }}
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover,
    QLineEdit:hover, QPlainTextEdit:hover {{
        border-color: {t["border_strong"]};
    }}
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QLineEdit:focus, QPlainTextEdit:focus {{
        border-color: {t["accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox::down-arrow {{
        {_image(chevron_down)}
        width: 12px;
        height: 7px;
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {t["field"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 4px;
        outline: none;
        selection-background-color: {t["accent_soft"]};
        selection-color: {t["accent"]};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 18px;
        border: none;
        background: transparent;
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        {_image(chevron_up)}
        width: 10px;
        height: 6px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        {_image(chevron_down)}
        width: 10px;
        height: 6px;
    }}

    /* Checkboxes: the dialog is mostly these, so they carry the look. */
    QCheckBox {{
        color: {t["text"]};
        font-size: 10pt;
        spacing: 9px;
        padding: 3px 0;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border-radius: 5px;
        border: 1px solid {t["border_strong"]};
        background: {t["field"]};
    }}
    QCheckBox::indicator:hover {{
        border-color: {t["accent"]};
    }}
    QCheckBox::indicator:checked {{
        background: {t["accent"]};
        border-color: {t["accent"]};
        {_image(tick)}
    }}

    /* Buttons */
    QPushButton {{
        background: {t["field"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 10pt;
    }}
    QPushButton:hover {{
        border-color: {t["border_strong"]};
        background: {t["hover"]};
    }}
    QPushButton:default {{
        background: {t["accent"]};
        color: {t["accent_text"]};
        border-color: {t["accent"]};
        font-weight: 600;
    }}

    /* The language checklist */
    QListWidget {{
        background: {t["field"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 4px;
        outline: none;
        font-size: 10pt;
    }}
    QListWidget::item {{
        padding: 4px 6px;
        border-radius: 5px;
    }}
    QListWidget::item:hover {{
        background: {t["hover"]};
    }}
    QListWidget::item:selected {{
        background: {t["accent_soft"]};
        color: {t["accent"]};
    }}
    QListWidget::indicator {{
        width: 15px;
        height: 15px;
        border-radius: 4px;
        border: 1px solid {t["border_strong"]};
        background: {t["field"]};
    }}
    QListWidget::indicator:checked {{
        background: {t["accent"]};
        border-color: {t["accent"]};
        {_image(tick)}
    }}

    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QFrame#separator {{
        background: {t["border"]};
        max-height: 1px;
        border: none;
    }}
    QWidget#footer {{
        background: {t["card"]};
        border-top: 1px solid {t["border"]};
    }}

    /* Slim scrollbars — the single biggest tell of an unstyled Qt app. */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["border_strong"]};
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t["subtext"]};
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t["border_strong"]};
        border-radius: 4px;
        min-width: 28px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0;
        width: 0;
        border: none;
        background: transparent;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}

    QToolTip {{
        background: {t["card"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 9pt;
    }}
    """
