"""Réglages: a sidebar of categories, one scrollable page each.

It used to be a single flat QVBoxLayout — thirty-odd widgets, no scroll area,
`setMinimumSize(380, 480)`. The layout's natural height was well over a
thousand pixels, so as soon as the window manager capped the window Qt
compressed every row past its minimum and the word-wrapped hints printed on
top of each other. A dialog you cannot read is a dialog whose settings do not
exist, so: categories on the left, and every page inside a
`QScrollArea(widgetResizable=True)` that scrolls instead of squashing.

Paint comes from `theme.py` — scoped to these windows, never app-wide, because
the bubble and the ribbon draw themselves.

Mic: a picker over the real capture sources (see `audio.list_mics` — PipeWire
sources where there is a sound server, which is the only way a Bluetooth mic
is selectable at all, PortAudio devices otherwise), rescanned each time the
dialog opens. Stored by id, empty = system default. Languages: searchable
checklist of Whisper's 100 — empty = auto-detect, one = forced, several =
per-segment code-switching. Settings are read on the next take, no daemon
restart.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tuparles import privacy_policy, settings, telemetry, theme
from tuparles.audio import list_mics
from tuparles.languages import LANGUAGES

_NAV_WIDTH = 196


def _hint(text: str) -> QLabel:
    """Explanatory prose. Word-wrapped, which only behaves inside a resizable
    scroll area — a wrapped label in an over-full fixed layout is exactly what
    produced the overlapping text this dialog used to show."""
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    label.setWordWrap(True)
    return label


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


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
        self.setMinimumSize(460, 520)
        self.setStyleSheet(theme.stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(8)

        layout.addWidget(_section("Termes à masquer"))
        layout.addWidget(
            _hint(
                "Ces termes sont <b>retirés</b> de l'historique enregistré, comme "
                "les secrets et identifiants. Idéal pour les noms de projet ou de "
                "client confidentiels. La casse et les accents sont ignorés. "
                "Un terme par ligne."
            )
        )
        self._block = QPlainTextEdit()
        self._block.setPlainText(
            privacy_policy.terms_to_text(settings.get("pii_denylist_block"))
        )
        layout.addWidget(self._block)

        layout.addWidget(_section("Termes à signaler"))
        layout.addWidget(
            _hint(
                "Ces termes sont <b>signalés</b> mais jamais masqués automatiquement "
                "— tu gardes la main. Pour ce que tu veux surveiller sans l'effacer. "
                "Un terme par ligne."
            )
        )
        self._alert = QPlainTextEdit()
        self._alert.setPlainText(
            privacy_policy.terms_to_text(settings.get("pii_denylist_alert"))
        )
        layout.addWidget(self._alert)

        layout.addWidget(_section("Plancher d'anonymat"))
        layout.addWidget(
            _hint(
                "Pour le nuage de mots : un terme dit moins de fois que ce seuil "
                "n'apparaît pas dans les analyses (1 = aucun filtre)."
            )
        )
        self._floor = QSpinBox()
        self._floor.setRange(1, 50)
        self._floor.setValue(privacy_policy.analytics_min_count())
        layout.addWidget(self._floor)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        # Named explicitly: the standard-button text is French only when a Qt
        # translation happens to be installed, and this is a French surface.
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
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
        self.setMinimumSize(720, 480)
        self.resize(860, 600)
        self.setStyleSheet(theme.stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setFixedWidth(_NAV_WIDTH)
        self._pages = QStackedWidget()
        body.addWidget(self._nav)
        body.addWidget(self._pages, 1)
        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)

        self._build_mic_page()
        self._build_language_page()
        self._build_bubble_page()
        self._build_writing_page()
        self._build_decode_page()
        self._build_privacy_page()
        self._build_dev_page()
        self._nav.setCurrentRow(0)

        footer = QWidget()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 12, 22, 12)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        # Named explicitly: the standard-button text is French only when a Qt
        # translation happens to be installed, and this is a French surface.
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        footer_layout.addStretch(1)
        footer_layout.addWidget(buttons)
        root.addWidget(footer)

    # ---- page scaffolding -------------------------------------------------

    def _add_page(self, icon: str, title: str) -> QVBoxLayout:
        """Register a nav entry; return the layout to fill for its page.

        The scroll area is the whole point: `widgetResizable(True)` gives the
        inner widget a definite width (so wrapped hints compute a real height)
        and lets a tall page scroll rather than compress.
        """
        inner = QWidget()
        inner.setObjectName("page")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        self._pages.addWidget(scroll)
        self._nav.addItem(QListWidgetItem(f"{icon}   {title}"))
        return layout

    # ---- pages ------------------------------------------------------------

    def _build_mic_page(self) -> None:
        layout = self._add_page("🎤", "Micro")
        layout.addWidget(
            _hint(
                "Le micro de la dictée. « Système » suit le réglage par défaut du "
                "bureau. La liste est relue à chaque ouverture de cette fenêtre : "
                "un casque appairé après le lancement y est déjà."
            )
        )
        self._mic = QComboBox()
        self._mic.addItem("Système (par défaut)", None)
        current_mic = settings.get("input_device")
        for mic in list_mics(refresh=True):
            label = mic["label"] + ("  ·  défaut système" if mic["default"] else "")
            self._mic.addItem(label, mic["id"])
        if current_mic:
            i = self._mic.findData(current_mic)
            if i >= 0:
                self._mic.setCurrentIndex(i)
            else:  # configured mic not currently present
                self._mic.addItem(f"{current_mic}  ·  déconnecté", current_mic)
                self._mic.setCurrentIndex(self._mic.count() - 1)
        layout.addWidget(self._mic)

        layout.addWidget(_section("Repères de démarrage"))
        self._start_sound = QCheckBox("Bip au démarrage de la dictée")
        self._start_sound.setToolTip(
            "Un petit son confirme que la dictée a démarré — tu peux parler. "
            "Le repère visuel (bulle + onde) est toujours actif."
        )
        self._start_sound.setChecked(bool(settings.get("start_cue_sound")))
        layout.addWidget(self._start_sound)
        layout.addStretch(1)

    def _build_language_page(self) -> None:
        layout = self._add_page("🌍", "Langues")
        layout.addWidget(
            _hint(
                "Aucune = détection automatique. Une seule = forcée. "
                "Plusieurs = code-switching : la langue est détectée segment "
                "par segment, pour passer de l'une à l'autre en cours de phrase."
            )
        )
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
        layout.addWidget(self._list, 1)

        clear = QPushButton("Tout décocher (auto)")
        clear.clicked.connect(self._clear_all)
        layout.addWidget(clear)

    def _build_bubble_page(self) -> None:
        layout = self._add_page("💬", "Bulle")
        layout.addWidget(_section("Écran"))
        layout.addWidget(
            _hint(
                "Sur quel écran la bulle s'affiche. « Écran principal » par défaut ; "
                "épingle-la à un moniteur précis, suis la souris ou la fenêtre "
                "active, ou affiche-la sur tous les écrans à la fois. (Appliqué à "
                "la dictée suivante.)"
            )
        )
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

        layout.addWidget(_section("Bandeau d'aperçu"))
        layout.addWidget(
            _hint(
                "La vue complète s'étale en <b>largeur</b> le long du bas de l'écran "
                "avant d'ajouter une ligne, pour voir toute la prise (début compris) "
                "sans une tour qui recouvre le code."
            )
        )
        layout.addWidget(_field_label("Largeur (% de l'écran, 0 = pastille de 460 px)"))
        self._ribbon_width = QSpinBox()
        self._ribbon_width.setRange(0, 100)
        self._ribbon_width.setSuffix(" %")
        # Stored as a 0..1 fraction; the spin box speaks whole percents.
        self._ribbon_width.setValue(
            round(float(settings.get("bubble_max_width")) * 100)
        )
        layout.addWidget(self._ribbon_width)

        layout.addWidget(
            _field_label("Lignes (1 = une seule ligne, sans historique compressé)")
        )
        self._ribbon_lines = QSpinBox()
        self._ribbon_lines.setRange(1, 3)
        self._ribbon_lines.setValue(int(settings.get("bubble_lines")))
        layout.addWidget(self._ribbon_lines)

        layout.addWidget(_field_label("Taille du texte (pt)"))
        self._ribbon_font = QDoubleSpinBox()
        self._ribbon_font.setRange(8.0, 24.0)
        self._ribbon_font.setSingleStep(0.5)
        self._ribbon_font.setValue(float(settings.get("bubble_font_pt")))
        layout.addWidget(self._ribbon_font)

        layout.addWidget(_section("Barre des tâches"))
        self._tray_anim = QCheckBox("Icône animée dans la barre des tâches")
        self._tray_anim.setToolTip(
            "L'icône respire doucement (et s'anime pendant la dictée). "
            "Décoche si ton bureau rame avec les mises à jour d'icône."
        )
        self._tray_anim.setChecked(bool(settings.get("tray_animation")))
        layout.addWidget(self._tray_anim)
        layout.addStretch(1)

    def _build_writing_page(self) -> None:
        layout = self._add_page("✍️", "Écriture")
        layout.addWidget(_section("Style d'écriture"))
        layout.addWidget(
            _hint(
                "Comment la casse de ta dictée est rendue. <b>Préservé</b> respecte "
                "ce que tu dis (par défaut) ; <b>minuscules</b> met tout en bas de "
                "casse (sigles et identifiants protégés) ; <b>Phrase</b> met une "
                "majuscule en début de phrase. Réglage repris de « Comment tu "
                "parles ? »."
            )
        )
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

        layout.addWidget(_section("Livraison"))
        layout.addWidget(
            _hint(
                "TuParles colle via le presse-papiers, ce qui écrase ce que tu avais "
                "copié. Coché, on le sauvegarde et on le remet après le collage — "
                "uniquement s'il s'agit de texte (jamais une image ou des fichiers, "
                "qu'un retour en texte détruirait). Contrepartie : le texte dicté "
                "n'est plus laissé dans le presse-papiers pour un re-collage manuel."
            )
        )
        self._clipboard_restore = QCheckBox("Préserver le presse-papiers")
        self._clipboard_restore.setChecked(bool(settings.get("clipboard_restore")))
        layout.addWidget(self._clipboard_restore)
        layout.addStretch(1)

    def _build_decode_page(self) -> None:
        layout = self._add_page("⚡", "Décodage")
        layout.addWidget(
            _hint(
                "Comment la parole est transformée en texte. Tout tourne en local ; "
                "ces réglages arbitrent vitesse, qualité et charge machine."
            )
        )

        layout.addWidget(_section("Aperçu en direct"))
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

        layout.addWidget(_section("Audio avant décodage"))
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

        self._speech_leveler = QCheckBox("Égaliser le niveau de la voix")
        self._speech_leveler.setToolTip(
            "Compense une voix basse même quand un bruit fort (clac de clavier, "
            "souffle) fausserait la normalisation classique : le niveau est "
            "égalisé image par image avant chaque décodage, aperçus comme "
            "transcription finale. Vérifié sur les prises réelles : aucun effet "
            "sur les prises normales, nette amélioration sur les prises faibles."
        )
        self._speech_leveler.setChecked(bool(settings.get("speech_leveler")))
        layout.addWidget(self._speech_leveler)

        layout.addWidget(_section("Rattrapage"))
        self._quiet_rescue = QCheckBox("Rattraper les prises parlées trop bas")
        self._quiet_rescue.setToolTip(
            "Quand la transcription finale perd des morceaux que l'aperçu en "
            "direct avait pourtant captés (voix basse + un clac de clavier qui "
            "fausse la normalisation), redécode automatiquement une copie au "
            "niveau corrigé et garde le résultat le plus complet. Se déclenche "
            "rarement, ne rend jamais une prise pire."
        )
        self._quiet_rescue.setChecked(bool(settings.get("quiet_rescue")))
        layout.addWidget(self._quiet_rescue)
        layout.addStretch(1)

    def _build_privacy_page(self) -> None:
        layout = self._add_page("🔒", "Vie privée")
        layout.addWidget(_section("Suivi d'usage"))
        layout.addWidget(
            _hint(
                "Le suivi d'usage est <b>100 % local</b> : il sert à voir quelles "
                "fonctions tu utilises vraiment, et ne quitte jamais ta machine. "
                "Décoche pour tout désactiver."
            )
        )
        self._telemetry = QCheckBox("Suivi d'usage local")
        self._telemetry.setChecked(telemetry.enabled())
        layout.addWidget(self._telemetry)
        forget = QPushButton("Effacer mes statistiques d'usage")
        forget.clicked.connect(self._forget_telemetry)
        layout.addWidget(forget)

        layout.addWidget(_section("Pare-feu PII"))
        layout.addWidget(
            _hint(
                "Le <b>pare-feu PII</b> masque les secrets et identifiants vérifiés "
                "(IBAN, n° de sécu, carte, clés d'API) <b>avant l'enregistrement</b> "
                "dans l'historique. Le texte dicté est toujours collé tel quel : "
                "seule la <i>copie conservée</i> est nettoyée. Attention, c'est "
                "<b>irréversible</b> — la donnée masquée n'est pas gardée."
            )
        )
        self._redact = QCheckBox("Masquer les PII dans l'historique")
        self._redact.setChecked(bool(settings.get("pii_redact_history")))
        layout.addWidget(self._redact)
        denylist_btn = QPushButton("Termes à masquer / signaler…")
        denylist_btn.clicked.connect(self._open_privacy)
        layout.addWidget(denylist_btn)
        layout.addStretch(1)

    def _build_dev_page(self) -> None:
        layout = self._add_page("🛠", "Dev")
        layout.addWidget(
            _hint(
                "Le <b>mode dev</b> enregistre l'<b>audio brut non masqué</b> de "
                "chaque dictée sur le disque (local, jamais synchronisé) pour rejouer "
                "un correctif. C'est ta <b>voix réelle</b>, pas le texte nettoyé — "
                "laisse décoché sauf si tu déboggues. Quand c'est actif, un point "
                "rouge reste affiché dans la barre des tâches."
            )
        )
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
        layout.addStretch(1)

    # ---- behaviour --------------------------------------------------------

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
        settings.put("quiet_rescue", self._quiet_rescue.isChecked())
        settings.put("speech_leveler", self._speech_leveler.isChecked())
        settings.put("clipboard_restore", self._clipboard_restore.isChecked())
        settings.put("bubble_screen", self._screen.currentData())
        settings.put("bubble_max_width", self._ribbon_width.value() / 100)
        settings.put("bubble_lines", self._ribbon_lines.value())
        settings.put("bubble_font_pt", self._ribbon_font.value())
        telemetry.set_enabled(self._telemetry.isChecked())
        settings.put("pii_redact_history", self._redact.isChecked())
        settings.put("dev_recording", self._dev_recording.isChecked())
        self.accept()
