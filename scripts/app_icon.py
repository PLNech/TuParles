"""Render the app icon from the same bars as the tray glyph — one identity.

Usage:  QT_QPA_PLATFORM=offscreen poetry run python scripts/app_icon.py
Output: packaging/tuparles.png (256x256)
"""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parents[1] / "packaging" / "tuparles.png"

_BG = QColor(17, 19, 27)
_ACCENT = QColor(122, 162, 247)
_BAR_HEIGHTS = (0.45, 0.85, 0.60)  # same frozen breath as the tray glyph


def main() -> None:
    QApplication(sys.argv)
    size = 256
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(_BG)
    p.drawRoundedRect(QRectF(0, 0, size, size), 58, 58)

    p.setBrush(_ACCENT)
    bar_w, gap = 36, 26
    x = (size - (bar_w * 3 + gap * 2)) / 2
    for h in _BAR_HEIGHTS:
        half = h * 88
        p.drawRoundedRect(QRectF(x, size / 2 - half, bar_w, half * 2), 16, 16)
        x += bar_w + gap
    p.end()

    OUT.parent.mkdir(exist_ok=True)
    pm.save(str(OUT))
    print(f"{OUT} ({size}x{size})")


if __name__ == "__main__":
    main()
