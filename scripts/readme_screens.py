"""Render README screenshots from the real widgets — no doctored mockups.

Usage:  QT_QPA_PLATFORM=offscreen poetry run python scripts/readme_screens.py
Output: .github/*.png (kept light; regenerate after any UI change)
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parents[1] / ".github"

RECORDING_TEXT = (
    "…on ship le feature d'abord, then we iterate sur les retours, virgule"
)
FULL_TEXT = (
    "Alors l'idée c'est simple : on garde le daemon local, the GPU does the "
    "heavy lifting en moins d'une seconde, et le texte arrive direct dans la "
    "fenêtre active. Pas de cloud, pas de latence réseau, just ton i9 et la "
    "4080 qui bossent pendant que tu parles. Et si le modèle se trompe sur "
    "max_tokens ou sur un nom propre, le lexique corrige au vol."
)
FINAL_TEXT = "C'est exactement ça, on ship le feature et on itère. 🎯"


def _wave(i: int) -> float:
    return abs(math.sin(i * 0.55) * 0.75 + math.sin(i * 1.7) * 0.2)


def _snap(widget, path: Path) -> None:
    pm = QPixmap(widget.size())
    pm.fill(Qt.transparent)
    widget.render(pm)
    pm.save(str(path))
    print(f"  {path.relative_to(OUT.parent)}  {pm.width()}x{pm.height()}")


def _dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(30, 32, 43))
    pal.setColor(QPalette.WindowText, QColor(205, 214, 244))
    pal.setColor(QPalette.Base, QColor(24, 26, 35))
    pal.setColor(QPalette.Text, QColor(205, 214, 244))
    pal.setColor(QPalette.Button, QColor(30, 32, 43))
    pal.setColor(QPalette.ButtonText, QColor(205, 214, 244))
    pal.setColor(QPalette.Highlight, QColor(122, 162, 247))
    pal.setColor(QPalette.HighlightedText, QColor(17, 19, 27))
    app.setPalette(pal)


def main() -> None:
    app = QApplication(sys.argv)
    _dark_palette(app)
    OUT.mkdir(exist_ok=True)

    from tuparles.ui import BAR_COUNT, Bubble

    print("Rendering bubbles…")
    bubble = Bubble(level_source=lambda: 0.0)
    bubble._levels.extend(_wave(i) for i in range(BAR_COUNT))
    bubble._set(state="recording", text=RECORDING_TEXT)
    _snap(bubble, OUT / "bubble-recording.png")

    bubble._set(state="final", text=FINAL_TEXT)
    _snap(bubble, OUT / "bubble-final.png")

    full = Bubble(level_source=lambda: 0.0, view="full")
    full._levels.extend(_wave(i + 7) for i in range(BAR_COUNT))
    full._set(state="recording", text=FULL_TEXT)
    _snap(full, OUT / "bubble-full.png")

    print("Rendering tray menu…")
    from tuparles.tray import Tray

    tray = Tray()
    menu = tray._menu
    menu.show()  # offscreen: forces layout, nothing appears anywhere
    menu.adjustSize()
    _snap(menu, OUT / "tray-menu.png")

    print("Rendering settings dialog…")
    # Isolated config so the render never touches the user's real settings.
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "tuparles"
        cfg.mkdir()
        (cfg / "settings.json").write_text(
            json.dumps({"languages": ["fr", "en"]})
        )
        os.environ["XDG_CONFIG_HOME"] = tmp
        from tuparles.settings_ui import SettingsDialog

        dlg = SettingsDialog()
        dlg.show()
        dlg.adjustSize()
        _snap(dlg, OUT / "settings-langues.png")

    print("Done.")


if __name__ == "__main__":
    main()
