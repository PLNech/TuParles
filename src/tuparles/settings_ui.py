"""Settings dialog: microphone + language selection.

Mic: a picker over the input devices, rescanned each time the dialog opens
(so a headset plugged in after launch shows up). The mic is stored by name,
empty = system default. Languages: searchable checklist of Whisper's 100 —
empty = auto-detect, one = forced, several = per-segment code-switching.
Settings are read on the next take, no daemon restart.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from tuparles import settings, telemetry
from tuparles.audio import list_input_devices
from tuparles.languages import LANGUAGES


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TuParles — Réglages")
        self.setMinimumSize(380, 480)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Microphone</b>"))
        mic_hint = QLabel(
            "Le micro de la dictée. « Système » suit le réglage par défaut "
            "du bureau. Un casque branché après le lancement apparaît à "
            "l'ouverture de cette fenêtre."
        )
        mic_hint.setWordWrap(True)
        layout.addWidget(mic_hint)
        self._mic = QComboBox()
        self._mic.addItem("Système (par défaut)", None)
        current_mic = settings.get("input_device")
        for dev in list_input_devices(refresh=True):
            label = dev["name"] + ("  ·  défaut système" if dev["default"] else "")
            self._mic.addItem(label, dev["name"])
        if current_mic:
            i = self._mic.findData(current_mic)
            if i >= 0:
                self._mic.setCurrentIndex(i)
            else:  # configured mic not currently present
                self._mic.addItem(f"{current_mic}  ·  déconnecté", current_mic)
                self._mic.setCurrentIndex(self._mic.count() - 1)
        layout.addWidget(self._mic)

        layout.addWidget(QLabel("<b>Langues de dictée</b>"))
        hint = QLabel(
            "Aucune = détection automatique. Une seule = forcée. "
            "Plusieurs = code-switching : la langue est détectée segment "
            "par segment, pour passer de l'une à l'autre en cours de phrase."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._search = QLineEdit(placeholderText="Filtrer… (nom ou code)")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        self._list = QListWidget()
        selected = set(settings.get("languages") or [])
        # Selected first, then the crowd alphabetically.
        ordered = sorted(
            LANGUAGES.items(), key=lambda kv: (kv[0] not in selected, kv[1])
        )
        for code, name in ordered:
            item = QListWidgetItem(f"{name}  ({code})")
            item.setData(Qt.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if code in selected else Qt.Unchecked)
            self._list.addItem(item)
        layout.addWidget(self._list)

        clear = QPushButton("Tout décocher (auto)")
        clear.clicked.connect(self._clear_all)
        layout.addWidget(clear)

        layout.addWidget(QLabel("<b>Confidentialité</b>"))
        privacy_hint = QLabel(
            "Le suivi d'usage est <b>100 % local</b> : il sert à voir quelles "
            "fonctions tu utilises vraiment, et ne quitte jamais ta machine. "
            "Décoche pour tout désactiver."
        )
        privacy_hint.setWordWrap(True)
        layout.addWidget(privacy_hint)
        self._telemetry = QCheckBox("Suivi d'usage local")
        self._telemetry.setChecked(telemetry.enabled())
        layout.addWidget(self._telemetry)
        forget = QPushButton("Effacer mes statistiques d'usage")
        forget.clicked.connect(self._forget_telemetry)
        layout.addWidget(forget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(needle not in item.text().casefold())

    def _clear_all(self) -> None:
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.Unchecked)

    def _forget_telemetry(self) -> None:
        """Wipe the local usage log — irreversible, so confirm first."""
        confirm = QMessageBox.question(
            self,
            "Effacer les statistiques",
            "Effacer définitivement tes statistiques d'usage locales ?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            removed = telemetry.clear()
            QMessageBox.information(
                self, "Effacé", f"{removed} évènement(s) supprimé(s)."
            )

    def _save(self) -> None:
        codes = [
            self._list.item(i).data(Qt.UserRole)
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.Checked
        ]
        settings.put("languages", codes)
        settings.put("input_device", self._mic.currentData())
        telemetry.set_enabled(self._telemetry.isChecked())
        self.accept()
