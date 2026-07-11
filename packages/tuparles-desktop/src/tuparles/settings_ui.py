"""Settings dialog: microphone + language selection.

Mic: a picker over the input devices, rescanned each time the dialog opens
(so a headset plugged in after launch shows up). The mic is stored by name,
empty = system default. Languages: searchable checklist of Whisper's 100 —
empty = auto-detect, one = forced, several = per-segment code-switching.
Settings are read on the next take, no daemon restart.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
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

        self._start_sound = QCheckBox("Bip au démarrage de la dictée")
        self._start_sound.setToolTip(
            "Un petit son confirme que la dictée a démarré — tu peux parler. "
            "Le repère visuel (bulle + onde) est toujours actif."
        )
        self._start_sound.setChecked(bool(settings.get("start_cue_sound")))
        layout.addWidget(self._start_sound)

        self._tray_anim = QCheckBox("Icône animée dans la barre des tâches")
        self._tray_anim.setToolTip(
            "L'icône respire doucement (et s'anime pendant la dictée). "
            "Décoche si ton bureau rame avec les mises à jour d'icône."
        )
        self._tray_anim.setChecked(bool(settings.get("tray_animation")))
        layout.addWidget(self._tray_anim)

        self._cpu_partials = QCheckBox("Aperçu en direct sur CPU")
        self._cpu_partials.setToolTip(
            "Affiche le texte au fil de la parole même sans GPU, via un petit "
            "modèle CPU (téléchargé une fois). Décoche sur une machine peu "
            "puissante — la bulle garde alors l'onde sonore. (Le GPU n'est pas "
            "concerné : il a toujours l'aperçu.)"
        )
        self._cpu_partials.setChecked(bool(settings.get("cpu_partials_enabled")))
        layout.addWidget(self._cpu_partials)

        self._backend_toast = QCheckBox("Prévenir au passage GPU → CPU")
        self._backend_toast.setToolTip(
            "Si le GPU lâche en cours de session, une note te le dit une fois "
            "(« Passé sur CPU — un peu plus lent »). Les barres passent de vert "
            "à bleu de toute façon ; ceci explique pourquoi."
        )
        self._backend_toast.setChecked(bool(settings.get("backend_toast")))
        layout.addWidget(self._backend_toast)

        self._trim_silence = QCheckBox("Couper les silences en début/fin de prise")
        self._trim_silence.setToolTip(
            "Retire le silence avant le premier mot et après le dernier, pour "
            "décoder plus vite — surtout sans GPU, où chaque seconde muette est "
            "décodée pour rien. Prudent : garde une marge (0,2 s au début, 0,4 s "
            "à la fin), ne touche jamais aux pauses internes, et conserve la prise "
            "entière au moindre doute (résultat trop court ou trop rogné)."
        )
        self._trim_silence.setChecked(bool(settings.get("trim_silence")))
        layout.addWidget(self._trim_silence)

        self._clipboard_restore = QCheckBox("Préserver le presse-papiers")
        self._clipboard_restore.setToolTip(
            "TuParles colle via le presse-papiers, ce qui écrase ce que tu avais "
            "copié. Coché, on le sauvegarde et on le remet après le collage — "
            "uniquement s'il s'agit de texte (jamais une image ou des fichiers, "
            "qu'un retour en texte détruirait). Contrepartie : le texte dicté "
            "n'est plus laissé dans le presse-papiers pour un re-collage manuel."
        )
        self._clipboard_restore.setChecked(bool(settings.get("clipboard_restore")))
        layout.addWidget(self._clipboard_restore)

        layout.addWidget(QLabel("<b>Écran de la bulle</b>"))
        screen_hint = QLabel(
            "Sur quel écran la bulle s'affiche. « Écran principal » par défaut ; "
            "épingle-la à un moniteur précis, suis la souris ou la fenêtre active, "
            "ou affiche-la sur tous les écrans à la fois. (Appliqué à la dictée "
            "suivante.)"
        )
        screen_hint.setWordWrap(True)
        layout.addWidget(screen_hint)
        self._screen = QComboBox()
        self._screen.addItem("Écran principal", "primary")
        self._screen.addItem("Suivre la souris", "cursor")
        self._screen.addItem("Suivre la fenêtre active", "focus")
        self._screen.addItem("Sur tous les écrans", "all")
        for s in QApplication.screens():
            geo = s.geometry()
            self._screen.addItem(
                f"Écran : {s.name()}  ({geo.width()}×{geo.height()})", s.name()
            )
        current_screen = settings.get("bubble_screen") or "primary"
        i = self._screen.findData(current_screen)
        if i >= 0:
            self._screen.setCurrentIndex(i)
        else:  # pinned monitor not currently connected
            self._screen.addItem(f"{current_screen}  ·  déconnecté", current_screen)
            self._screen.setCurrentIndex(self._screen.count() - 1)
        layout.addWidget(self._screen)

        layout.addWidget(QLabel("<b>Bandeau d'aperçu</b>"))
        ribbon_hint = QLabel(
            "La vue complète s'étale en <b>largeur</b> le long du bas de l'écran "
            "avant d'ajouter une ligne, pour voir toute la prise (début compris) "
            "sans une tour qui recouvre le code. « Largeur » = part de l'écran "
            "occupée (0 % = petite pastille fixe de 460 px) ; « Lignes » plafonne "
            "la hauteur (1 = une seule ligne, sans historique compressé)."
        )
        ribbon_hint.setWordWrap(True)
        layout.addWidget(ribbon_hint)

        layout.addWidget(QLabel("Largeur du bandeau (% de l'écran, 0 = pastille)"))
        self._ribbon_width = QSpinBox()
        self._ribbon_width.setRange(0, 100)
        self._ribbon_width.setSuffix(" %")
        # Stored as a 0..1 fraction; the spin box speaks whole percents.
        self._ribbon_width.setValue(
            round(float(settings.get("bubble_max_width")) * 100)
        )
        layout.addWidget(self._ribbon_width)

        layout.addWidget(QLabel("Lignes du bandeau"))
        self._ribbon_lines = QSpinBox()
        self._ribbon_lines.setRange(1, 3)
        self._ribbon_lines.setValue(int(settings.get("bubble_lines")))
        layout.addWidget(self._ribbon_lines)

        layout.addWidget(QLabel("Taille du texte (pt)"))
        self._ribbon_font = QDoubleSpinBox()
        self._ribbon_font.setRange(8.0, 24.0)
        self._ribbon_font.setSingleStep(0.5)
        self._ribbon_font.setValue(float(settings.get("bubble_font_pt")))
        layout.addWidget(self._ribbon_font)

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

        layout.addWidget(QLabel("<b>Style d'écriture</b>"))
        casing_hint = QLabel(
            "Comment la casse de ta dictée est rendue. <b>Préservé</b> respecte "
            "ce que tu dis (par défaut) ; <b>minuscules</b> met tout en bas de "
            "casse (sigles et identifiants protégés) ; <b>Phrase</b> met une "
            "majuscule en début de phrase. Réglage repris de « Comment tu parles ? »."
        )
        casing_hint.setWordWrap(True)
        layout.addWidget(casing_hint)
        self._casing = QComboBox()
        # Same axis the onboarding card writes — share its labels so the two
        # surfaces can never disagree about what a style is called.
        from tuparles.onboarding import AXES

        casing_axis = next(a for a in AXES if a.key == "casing_style")
        for choice in casing_axis.choices:
            self._casing.addItem(choice.label, choice.value)
        current_style = settings.get("casing_style")
        i = self._casing.findData(current_style)
        if i >= 0:
            self._casing.setCurrentIndex(i)
        layout.addWidget(self._casing)

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

        dev_hint = QLabel(
            "Le <b>mode dev</b> enregistre l'<b>audio brut non masqué</b> de "
            "chaque dictée sur le disque (local, jamais synchronisé) pour rejouer "
            "un correctif. C'est ta <b>voix réelle</b>, pas le texte nettoyé — "
            "laisse décoché sauf si tu déboggues. Quand c'est actif, un point "
            "rouge reste affiché dans la barre des tâches."
        )
        dev_hint.setWordWrap(True)
        layout.addWidget(dev_hint)
        self._dev_recording = QCheckBox("Mode dev — enregistrer l'audio brut")
        self._dev_recording.setToolTip(
            "Enregistre ta voix non masquée localement (takes/<id>.wav), pour "
            "rejouer un correctif. La variable TUPARLES_DEV reste prioritaire."
        )
        # Reflect the EFFECTIVE state (env override may force it on/off), but the
        # checkbox writes only the setting — the env var is the dev's own lever.
        from tuparles import takes

        self._dev_recording.setChecked(takes.dev_recording_enabled())
        layout.addWidget(self._dev_recording)

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
        settings.put("casing_style", self._casing.currentData())
        settings.put("start_cue_sound", self._start_sound.isChecked())
        settings.put("tray_animation", self._tray_anim.isChecked())
        settings.put("cpu_partials_enabled", self._cpu_partials.isChecked())
        settings.put("backend_toast", self._backend_toast.isChecked())
        settings.put("trim_silence", self._trim_silence.isChecked())
        settings.put("clipboard_restore", self._clipboard_restore.isChecked())
        settings.put("bubble_screen", self._screen.currentData())
        settings.put("bubble_max_width", self._ribbon_width.value() / 100)
        settings.put("bubble_lines", self._ribbon_lines.value())
        settings.put("bubble_font_pt", self._ribbon_font.value())
        telemetry.set_enabled(self._telemetry.isChecked())
        settings.put("pii_redact_history", self._redact.isChecked())
        settings.put("dev_recording", self._dev_recording.isChecked())
        self.accept()
