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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from tuparles import privacy_policy, settings, telemetry
from tuparles.audio import list_input_devices
from tuparles.languages import LANGUAGES


class PrivacyDialog(QDialog):
    """The denylist editor for the PII firewall (#107).

    Two tiers, one textarea each: BLOCK terms are masked from the stored record
    (the asymmetric, redact-by-default tier), ALERT terms are surfaced but never
    auto-redacted (the reversible, "you decide" tier). Plus the analytics
    k-floor. Operator profiles / faker / cloud-egress knobs arrive with the
    reversible LLM firewall (#105); this panel covers the deterministic core.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TuParles — Pare-feu PII")
        self.setMinimumSize(420, 460)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Termes à masquer</b> (un par ligne)"))
        block_hint = QLabel(
            "Ces termes sont <b>retirés</b> de l'historique enregistré, comme "
            "les secrets et identifiants. Idéal pour les noms de projet ou de "
            "client confidentiels. La casse et les accents sont ignorés."
        )
        block_hint.setWordWrap(True)
        layout.addWidget(block_hint)
        self._block = QPlainTextEdit()
        self._block.setPlainText(
            privacy_policy.terms_to_text(settings.get("pii_denylist_block"))
        )
        layout.addWidget(self._block)

        layout.addWidget(QLabel("<b>Termes à signaler</b> (un par ligne)"))
        alert_hint = QLabel(
            "Ces termes sont <b>signalés</b> mais jamais masqués automatiquement "
            "— tu gardes la main. Pour ce que tu veux surveiller sans l'effacer."
        )
        alert_hint.setWordWrap(True)
        layout.addWidget(alert_hint)
        self._alert = QPlainTextEdit()
        self._alert.setPlainText(
            privacy_policy.terms_to_text(settings.get("pii_denylist_alert"))
        )
        layout.addWidget(self._alert)

        floor_hint = QLabel(
            "<b>Plancher d'anonymat</b> pour le nuage de mots : un terme dit "
            "moins de fois que ce seuil n'apparaît pas dans les analyses "
            "(1 = aucun filtre)."
        )
        floor_hint.setWordWrap(True)
        layout.addWidget(floor_hint)
        self._floor = QSpinBox()
        self._floor.setRange(1, 50)
        self._floor.setValue(privacy_policy.analytics_min_count())
        layout.addWidget(self._floor)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        settings.put(
            "pii_denylist_block", privacy_policy.parse_terms(self._block.toPlainText())
        )
        settings.put(
            "pii_denylist_alert", privacy_policy.parse_terms(self._alert.toPlainText())
        )
        settings.put("pii_analytics_min_count", self._floor.value())
        self.accept()


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

        redact_hint = QLabel(
            "Le <b>pare-feu PII</b> masque les secrets et identifiants vérifiés "
            "(IBAN, n° de sécu, carte, clés d'API) <b>avant l'enregistrement</b> "
            "dans l'historique. Le texte dicté est toujours collé tel quel : "
            "seule la <i>copie conservée</i> est nettoyée. Attention, c'est "
            "<b>irréversible</b> — la donnée masquée n'est pas gardée."
        )
        redact_hint.setWordWrap(True)
        layout.addWidget(redact_hint)
        self._redact = QCheckBox("Masquer les PII dans l'historique")
        self._redact.setChecked(bool(settings.get("pii_redact_history")))
        layout.addWidget(self._redact)
        denylist_btn = QPushButton("Termes à masquer / signaler…")
        denylist_btn.clicked.connect(self._open_privacy)
        layout.addWidget(denylist_btn)

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

    def _open_privacy(self) -> None:
        PrivacyDialog(self).exec()

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
        settings.put("pii_redact_history", self._redact.isChecked())
        self.accept()
