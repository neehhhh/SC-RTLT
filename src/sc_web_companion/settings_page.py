from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .hud_color import (
    DEFAULT_HUD_COLOR,
    HUD_COLOR_SETTINGS_KEY,
    HUD_SECONDARY_COLOR_SETTINGS_KEY,
    hud_theme_colors,
    normalize_hud_color,
    normalize_hud_secondary_color,
)
from .language import current_language, tr
from .public_parser_recorder import public_parser_output_path
from .radio_engine import RadioEngine, available_output_devices
from .radio_page import DEFAULT_STATION_ID, HCN_STATIONS, STATION_BY_ID
from .theme_loader import install_theme_file, load_theme_file, remove_installed_theme
from .verse_time import VERSE_LOCATIONS, normalize_location_id


class SettingsPage(QWidget):
    settings_changed = Signal()
    reset_widget_geometry_requested = Signal()
    edit_hud_layout_requested = Signal()
    clear_browser_data_requested = Signal()
    clear_credentials_requested = Signal()

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.language_at_creation = current_language(settings)
        t = self._t
        self.audio_test = RadioEngine(
            self.settings.value("radio/volume", 35, type=int),
            self,
            self.settings.value("radio/output_device", "", type=str),
        )

        title = QLabel(t("Réglages", "Settings"))
        title.setObjectName("homeTitle")
        subtitle = QLabel(t("Widget, navigation web, comptes, heure du Verse et sortie audio.", "Widget, web navigation, accounts, Verse time and audio output."))
        subtitle.setObjectName("homeSubtitle")

        self.widget_variant = QComboBox()
        self.widget_variant.addItem("Widget", "widget")
        self.widget_variant.setCurrentIndex(0)
        variant_note = QLabel(
            t(
                "Le widget conserve toujours sa disposition normale. La réduction automatique et le mode Mini sont désactivés.",
                "The widget always keeps its normal layout. Automatic collapse and Mini mode are disabled.",
            )
        )
        variant_note.setWordWrap(True)
        variant_note.setObjectName("homeSubtitle")

        self.auto_widget = QCheckBox(t("Passer automatiquement en widget après inactivité", "Switch to widget automatically after inactivity"))
        self.auto_widget.setChecked(self.settings.value("widget/auto_enabled", True, type=bool))
        self.auto_delay = QSpinBox()
        self.auto_delay.setRange(5, 3600)
        self.auto_delay.setSuffix(" s")
        self.auto_delay.setValue(self.settings.value("widget/auto_delay_seconds", 30, type=int))
        self.start_widget = QCheckBox(t("Démarrer dans le dernier mode utilisé", "Start in the last used mode"))
        self.start_widget.setChecked(self.settings.value("widget/remember_mode", True, type=bool))
        self.always_on_top = QCheckBox(t("Toujours au-dessus : application et widget", "Always on top: application and widget"))
        self.always_on_top.setChecked(self.settings.value("widget/always_on_top", True, type=bool))
        self.auto_hide_game_ui = QCheckBox(
            t("Masquer le widget pendant les interfaces de Star Citizen", "Hide the widget while Star Citizen interfaces are open")
        )
        self.auto_hide_game_ui.setChecked(
            self.settings.value("widget/auto_hide_game_ui_enabled", True, type=bool)
        )
        self.auto_hide_game_ui.setToolTip(
            t("Loot, mobiGlas, ASOP et consoles interactives. L’inventaire utilise le réglage dédié ci-dessous.", "Loot, mobiGlas, ASOP and interactive consoles. Inventory uses the dedicated setting below.")
        )
        self.hide_in_inventory = QCheckBox(
            t("Masquer le widget dans l’inventaire", "Hide the widget in inventory")
        )
        self.hide_in_inventory.setChecked(
            self.settings.value("widget/hide_in_inventory_enabled", True, type=bool)
        )
        self.hide_in_inventory.setToolTip(
            t("Masque temporairement le widget à l’ouverture de l’inventaire, puis le restaure à sa fermeture.", "Temporarily hides the widget when inventory opens, then restores it when inventory closes.")
        )
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        saved_opacity = self.settings.value("widget/background_opacity", self.settings.value("widget/window_opacity", 100))
        try:
            opacity_value = int(saved_opacity)
        except (TypeError, ValueError):
            opacity_value = 100
        self.opacity.setValue(max(5, min(100, opacity_value)))
        self.opacity_value = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(lambda value: self.opacity_value.setText(f"{value}%"))
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity, 1)
        opacity_row.addWidget(self.opacity_value)
        opacity_holder = QWidget()
        opacity_holder.setLayout(opacity_row)

        widget_form = QFormLayout()
        widget_form.addRow(variant_note)
        widget_form.addRow(self.auto_widget)
        widget_form.addRow(t("Délai avant widget", "Delay before widget"), self.auto_delay)
        widget_form.addRow(self.start_widget)
        widget_form.addRow(self.always_on_top)
        widget_form.addRow(self.auto_hide_game_ui)
        widget_form.addRow(self.hide_in_inventory)
        game_ui_note = QLabel(t("Détection locale et passive : événements précis de Game.log et état du curseur Windows. Aucune capture d’écran, lecture mémoire, injection ou interception des commandes du jeu.", "Local passive detection: precise Game.log events and Windows cursor state. No screenshots, memory reading, injection or interception of game controls."))
        game_ui_note.setWordWrap(True)
        game_ui_note.setObjectName("homeSubtitle")
        widget_form.addRow(game_ui_note)
        widget_form.addRow(t("Opacité du fond", "Background opacity"), opacity_holder)
        opacity_note = QLabel(t("Seul le fond illustré change : le texte, les boutons et le contour restent lisibles.", "Only the illustrated background changes; text, buttons and border remain readable."))
        opacity_note.setWordWrap(True)
        opacity_note.setObjectName("homeSubtitle")
        widget_form.addRow(opacity_note)

        self._hud_color = normalize_hud_color(
            self.settings.value(HUD_COLOR_SETTINGS_KEY, DEFAULT_HUD_COLOR, type=str)
        )
        saved_secondary = self.settings.value(
            HUD_SECONDARY_COLOR_SETTINGS_KEY, "", type=str
        ).strip()
        self._hud_secondary_color = (
            normalize_hud_secondary_color(saved_secondary)
            if saved_secondary
            else hud_theme_colors(self._hud_color)[1]
        )
        self.hud_color_swatch = QLabel()
        self.hud_color_swatch.setFixedSize(42, 22)
        self.hud_color_value = QLabel(self._hud_color)
        choose_hud_color = QPushButton(t("Choisir…", "Choose…"))
        choose_hud_color.clicked.connect(self._choose_hud_color)
        reset_hud_color = QPushButton(t("Bleu d’origine", "Default blue"))
        reset_hud_color.clicked.connect(self._reset_hud_color)
        hud_color_row = QHBoxLayout()
        hud_color_row.addWidget(self.hud_color_swatch)
        hud_color_row.addWidget(self.hud_color_value)
        hud_color_row.addWidget(choose_hud_color)
        hud_color_row.addWidget(reset_hud_color)
        hud_color_row.addStretch(1)
        hud_color_holder = QWidget()
        hud_color_holder.setLayout(hud_color_row)
        widget_form.addRow(t("Couleur principale du HUD", "Primary HUD colour"), hud_color_holder)

        self.hud_secondary_color_swatch = QLabel()
        self.hud_secondary_color_swatch.setFixedSize(42, 22)
        self.hud_secondary_color_value = QLabel(self._hud_secondary_color)
        choose_hud_secondary_color = QPushButton(t("Choisir…", "Choose…"))
        choose_hud_secondary_color.clicked.connect(self._choose_hud_secondary_color)
        reset_hud_secondary_color = QPushButton(t("Teinte liée", "Derived colour"))
        reset_hud_secondary_color.clicked.connect(self._reset_hud_secondary_color)
        hud_secondary_color_row = QHBoxLayout()
        hud_secondary_color_row.addWidget(self.hud_secondary_color_swatch)
        hud_secondary_color_row.addWidget(self.hud_secondary_color_value)
        hud_secondary_color_row.addWidget(choose_hud_secondary_color)
        hud_secondary_color_row.addWidget(reset_hud_secondary_color)
        hud_secondary_color_row.addStretch(1)
        hud_secondary_color_holder = QWidget()
        hud_secondary_color_holder.setLayout(hud_secondary_color_row)
        widget_form.addRow(
            t("Couleur secondaire du HUD", "Secondary HUD colour"),
            hud_secondary_color_holder,
        )
        hud_color_note = QLabel(
            t(
                "Les deux couleurs restent fixes jusqu’à leur modification ici. La principale colore les accents ; la secondaire colore les repères, les dégradés et les textes lumineux concernés. L’heure PC et le nom de la radio restent blancs. Les lieux, vaisseaux et constructeurs ne les changent plus automatiquement.",
                "Both colours stay fixed until changed here. The primary colour drives accents; the secondary colour drives guides, gradients and the applicable bright text. PC time and the radio name stay white. Locations, ships and manufacturers no longer change them automatically.",
            )
        )
        hud_color_note.setWordWrap(True)
        hud_color_note.setObjectName("homeSubtitle")
        widget_form.addRow(hud_color_note)
        self._update_hud_color_preview()

        reset_geometry = QPushButton(t("Réinitialiser la position du widget", "Reset widget position"))
        reset_geometry.clicked.connect(self.reset_widget_geometry_requested)
        widget_form.addRow(reset_geometry)
        edit_hud = QPushButton(t("Ouvrir l’éditeur du HUD", "Open HUD editor"))
        edit_hud.setToolTip(
            t(
                "Déplacer, recadrer et redimensionner proportionnellement tous les blocs et les deux barres bleues sur l’écran.",
                "Move, crop and proportionally resize every block and both blue bars across the screen.",
            )
        )
        edit_hud.clicked.connect(lambda _checked=False: self.edit_hud_layout_requested.emit())
        widget_form.addRow(edit_hud)

        self._theme_path = self.settings.value("theme/path", "", type=str).strip()
        self.theme_name_label = QLabel(self.settings.value("theme/name", t("Thème d’origine", "Default theme"), type=str))
        self.theme_name_label.setWordWrap(True)
        self.theme_name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        load_theme = QPushButton(t("Charger un fichier .style", "Load a .style file"))
        load_theme.clicked.connect(self._choose_theme)
        reset_theme = QPushButton(t("Thème d’origine", "Default theme"))
        reset_theme.clicked.connect(self._reset_theme)
        theme_actions = QHBoxLayout()
        theme_actions.addWidget(load_theme)
        theme_actions.addWidget(reset_theme)
        theme_actions.addStretch(1)
        theme_holder = QWidget()
        theme_holder.setLayout(theme_actions)
        widget_form.addRow(t("Thème chargé", "Loaded theme"), self.theme_name_label)
        widget_form.addRow(theme_holder)
        theme_note = QLabel(t("Les fichiers .style peuvent modifier l’apparence de l’application et les effets visuels du widget. La couleur du HUD reste celle choisie ci-dessus.", ".style files can change the application appearance and widget visual effects. The HUD colour remains the one selected above."))
        theme_note.setWordWrap(True)
        theme_note.setObjectName("homeSubtitle")
        widget_form.addRow(theme_note)

        self.keep_sessions = QCheckBox(t("Conserver les sessions, cookies et comptes reconnus", "Keep sessions, cookies and recognised accounts"))
        self.keep_sessions.setChecked(self.settings.value("browser/keep_sessions", True, type=bool))
        self.auto_fill_credentials = QCheckBox(t("Remplir automatiquement le coffre Windows", "Automatically fill from Windows vault"))
        self.auto_fill_credentials.setChecked(
            self.settings.value("browser/auto_fill_credentials", True, type=bool)
        )
        browser_note = QLabel(t("Les sessions utilisent le profil Chromium local de l'application. Les mots de passe sont facultatifs et chiffrés par Windows pour l'utilisateur connecté ; ils ne sont jamais stockés en clair ni synchronisés.", "Sessions use the application's local Chromium profile. Password storage is optional and encrypted by Windows for the signed-in user; credentials are never stored in plain text or synchronised."))
        browser_note.setWordWrap(True)
        browser_note.setObjectName("homeSubtitle")
        clear_browser = QPushButton(t("Effacer cookies, cache et sessions", "Clear cookies, cache and sessions"))
        clear_browser.clicked.connect(self.clear_browser_data_requested)
        clear_credentials = QPushButton(t("Effacer les identifiants du coffre Windows", "Clear Windows vault credentials"))
        clear_credentials.clicked.connect(self.clear_credentials_requested)
        browser_actions = QHBoxLayout()
        browser_actions.addWidget(clear_browser)
        browser_actions.addWidget(clear_credentials)
        browser_holder = QWidget()
        browser_holder.setLayout(browser_actions)
        browser_form = QFormLayout()
        browser_form.addRow(self.keep_sessions)
        browser_form.addRow(self.auto_fill_credentials)
        browser_form.addRow(browser_note)
        browser_form.addRow(browser_holder)

        self.location = QComboBox()
        for item in VERSE_LOCATIONS:
            self.location.addItem(item.label, item.location_id)
        saved_location = self.settings.value("verse_time/location", "", type=str)
        if not saved_location:
            saved_location = self.settings.value("verse_weather/location", "new-babbage", type=str)
        self.location.setCurrentIndex(max(0, self.location.findData(saved_location)))

        self.auto_game_location = QCheckBox(t("Détection automatique via Game.log", "Automatic detection through Game.log"))
        self.use_default_location = QCheckBox(t("Utiliser une ville par défaut", "Use a default city"))
        self.location_mode_group = QButtonGroup(self)
        self.location_mode_group.setExclusive(True)
        self.location_mode_group.addButton(self.auto_game_location)
        self.location_mode_group.addButton(self.use_default_location)
        saved_location_mode = self.settings.value("game_log/location_mode", "", type=str)
        if saved_location_mode in {"automatic", "default_city"}:
            automatic_location = saved_location_mode == "automatic"
        else:
            automatic_location = self.settings.value(
                "game_log/auto_location_enabled", True, type=bool
            )
        self.auto_game_location.setChecked(automatic_location)
        self.use_default_location.setChecked(not automatic_location)
        self.auto_game_location.toggled.connect(self._update_location_mode_controls)
        self.use_default_location.toggled.connect(self._update_location_mode_controls)
        self._update_location_mode_controls()
        self.public_parser_path = QLabel(str(public_parser_output_path()))
        self.public_parser_path.setWordWrap(True)
        self.public_parser_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._game_log_path = self.settings.value("game_log/path", "", type=str).strip()
        self.game_log_path_label = QLabel(self._game_log_path or t("Détection automatique", "Automatic detection"))
        self.game_log_path_label.setWordWrap(True)
        self.game_log_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        choose_game_log = QPushButton(t("Choisir Game.log", "Choose Game.log"))
        choose_game_log.clicked.connect(self._choose_game_log)
        game_log_path_row = QHBoxLayout()
        game_log_path_row.addWidget(self.game_log_path_label, 1)
        game_log_path_row.addWidget(choose_game_log)
        game_log_path_holder = QWidget()
        game_log_path_holder.setLayout(game_log_path_row)
        self.game_log_status = QLabel(
            self.settings.value("game_log/status", t("En attente de Game.log", "Waiting for Game.log"), type=str)
        )
        self.game_log_status.setWordWrap(True)
        self.game_log_status.setObjectName("homeSubtitle")

        verse_form = QFormLayout()
        verse_form.addRow(self.auto_game_location)
        verse_form.addRow(self.use_default_location)
        verse_form.addRow(t("Ville par défaut", "Default city"), self.location)
        verse_form.addRow(t("Fichier Public Real Time Checker", "Public Real Time Checker file"), self.public_parser_path)
        verse_form.addRow(t("Fichier du jeu", "Game file"), game_log_path_holder)
        verse_form.addRow(t("État", "Status"), self.game_log_status)
        verse_note = QLabel(t("Game.log reste lu localement et en lecture seule pour la localisation automatique. Aucun journal, nom de joueur ou identifiant de compte n'est copié. Un enregistrement est ajouté au fichier Public Real Time Checker uniquement lorsque vous appuyez sur le bouton Wi-Fi puis saisissez le lieu réel. Le fichier contient ce texte et le code de localisation le plus probable détecté dans Game.log.", "Game.log is still read locally and read-only for automatic location detection. No log, player name or account identifier is copied. A record is added to the Public Real Time Checker file only when you press the Wi-Fi button and enter the real place. The file contains that text and the most probable location code detected in Game.log."))
        verse_note.setWordWrap(True)
        verse_note.setObjectName("homeSubtitle")
        verse_form.addRow(verse_note)

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(self.settings.value("radio/volume", 35, type=int))
        self.volume.valueChanged.connect(self.audio_test.set_volume)
        self.output_device = QComboBox()
        self.output_device.addItem(t("Sortie audio Windows par défaut", "Default Windows audio output"), "")
        for label, device_id in available_output_devices():
            self.output_device.addItem(label, device_id)
        saved_device = self.settings.value("radio/output_device", "", type=str)
        self.output_device.setCurrentIndex(max(0, self.output_device.findData(saved_device)))
        self.output_device.currentIndexChanged.connect(self._update_test_device)

        self.station = QComboBox()
        for station in HCN_STATIONS:
            self.station.addItem(station.display_name, station.station_id)
        saved_station = self.settings.value("radio/station", DEFAULT_STATION_ID, type=str)
        self.station.setCurrentIndex(max(0, self.station.findData(saved_station)))
        self.station.currentIndexChanged.connect(self._station_selection_changed)
        self.test_sound_button = QPushButton(t("Tester la sortie audio", "Test audio output"))
        self.test_sound_button.clicked.connect(self._test_output)
        self.test_radio_button = QPushButton(t("Tester la station sélectionnée", "Test selected station"))
        self.test_radio_button.clicked.connect(self._test_radio)
        self.stop_test_button = QPushButton(t("Arrêter le test", "Stop test"))
        self.stop_test_button.clicked.connect(self.audio_test.stop)
        test_buttons = QHBoxLayout()
        test_buttons.addWidget(self.test_sound_button)
        test_buttons.addWidget(self.test_radio_button)
        test_buttons.addWidget(self.stop_test_button)
        test_holder = QWidget()
        test_holder.setLayout(test_buttons)
        self.audio_status = QLabel(t("Le test local permet de vérifier les haut-parleurs sans Internet.", "The local test checks your speakers without Internet access."))
        self.audio_status.setWordWrap(True)
        self.audio_status.setObjectName("homeSubtitle")
        self.audio_test.state_changed.connect(self._audio_state_changed)
        self.audio_test.error.connect(lambda text: self.audio_status.setText(f"{t('Erreur radio', 'Radio error')} : {text}"))
        self.audio_test.metadata_status_changed.connect(self._metadata_status_changed)
        self._station_selection_changed()

        radio_form = QFormLayout()
        radio_form.addRow(t("Station", "Station"), self.station)
        radio_form.addRow(t("Volume", "Volume"), self.volume)
        radio_form.addRow(t("Sortie audio", "Audio output"), self.output_device)
        radio_form.addRow(test_holder)
        radio_form.addRow(self.audio_status)
        radio_note = QLabel(t("Le flux audio et le flux de métadonnées de la radio sont vérifiés séparément. L'état affiché indique clairement lequel répond.", "The radio audio and metadata streams are checked separately. The displayed status clearly shows which one is responding."))
        radio_note.setWordWrap(True)
        radio_note.setObjectName("homeSubtitle")
        radio_form.addRow(radio_note)

        self.language = QComboBox()
        self.language.addItem("Français", "fr")
        self.language.addItem("English", "en")
        language_index = self.language.findData(current_language(self.settings))
        self.language.setCurrentIndex(max(0, language_index))

        self.start_with_windows = QCheckBox(t("Lancer Public Real Time Checker avec Windows", "Launch Public Real Time Checker with Windows"))
        self.start_with_windows.setChecked(self.settings.value("app/start_with_windows", False, type=bool))
        shortcut_note = QLabel(t("Radio : les commandes multimédia produites par Fn commandent précédente, lecture/pause et suivante. Les touches F10, F11 et F12 seules ne déclenchent rien. Widget : Ctrl+Alt+F8 réduit et Ctrl+Alt+F9 ouvre.", "Radio: multimedia commands produced by Fn control previous, play/pause and next. F10, F11 and F12 alone do nothing. Widget: Ctrl+Alt+F8 collapses and Ctrl+Alt+F9 opens."))
        shortcut_note.setWordWrap(True)
        shortcut_note.setObjectName("homeSubtitle")
        app_form = QFormLayout()
        app_form.addRow(t("Langue", "Language"), self.language)
        app_form.addRow(self.start_with_windows)
        app_form.addRow(shortcut_note)

        save_button = QPushButton(t("Enregistrer les réglages", "Save settings"))
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self.save)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._section(t("Widget", "Widget"), widget_form))
        layout.addWidget(self._section(t("Navigation et comptes", "Navigation and accounts"), browser_form))
        layout.addWidget(self._section(t("Heure Star Citizen", "Star Citizen time"), verse_form))
        layout.addWidget(self._section(t("Radio", "Radio"), radio_form))
        layout.addWidget(self._section(t("Windows", "Windows"), app_form))
        layout.addWidget(save_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _t(self, french: str, english: str) -> str:
        return tr(self.settings, french, english)

    def _update_hud_color_preview(self) -> None:
        self._hud_color = normalize_hud_color(self._hud_color)
        self._hud_secondary_color = normalize_hud_secondary_color(
            self._hud_secondary_color
        )
        self.hud_color_value.setText(self._hud_color)
        self.hud_color_swatch.setStyleSheet(
            f"background: {self._hud_color}; border: 1px solid rgba(255,255,255,150); border-radius: 4px;"
        )
        self.hud_secondary_color_value.setText(self._hud_secondary_color)
        self.hud_secondary_color_swatch.setStyleSheet(
            f"background: {self._hud_secondary_color}; border: 1px solid rgba(255,255,255,150); border-radius: 4px;"
        )

    def _choose_hud_color(self) -> None:
        selected = QColorDialog.getColor(
            QColor(self._hud_color),
            self,
            self._t("Choisir la couleur du HUD", "Choose HUD colour"),
        )
        if not selected.isValid():
            return
        selected.setAlpha(255)
        self._hud_color = normalize_hud_color(selected.name())
        self._update_hud_color_preview()

    def _reset_hud_color(self) -> None:
        self._hud_color = DEFAULT_HUD_COLOR
        self._update_hud_color_preview()

    def _choose_hud_secondary_color(self) -> None:
        selected = QColorDialog.getColor(
            QColor(self._hud_secondary_color),
            self,
            self._t("Couleur secondaire du HUD", "Secondary HUD colour"),
        )
        if not selected.isValid():
            return
        self._hud_secondary_color = normalize_hud_secondary_color(selected.name())
        self._update_hud_color_preview()

    def _reset_hud_secondary_color(self) -> None:
        self._hud_secondary_color = hud_theme_colors(self._hud_color)[1]
        self._update_hud_color_preview()

    @staticmethod
    def _section(title: str, form: QFormLayout) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsSection")
        box = QVBoxLayout(frame)
        box.setContentsMargins(16, 14, 16, 14)
        heading = QLabel(title)
        heading.setObjectName("settingsTitle")
        box.addWidget(heading)
        box.addLayout(form)
        return frame


    def _choose_theme(self) -> None:
        initial = self._theme_path or str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            self._t("Charger un thème Public Real Time Checker", "Load a Public Real Time Checker theme"),
            initial,
            self._t("Thèmes Public Real Time Checker (*.style *.scstyle *.json);;Styles QSS (*.qss);;Tous les fichiers (*)", "Public Real Time Checker themes (*.style *.scstyle *.json);;QSS styles (*.qss);;All files (*)"),
        )
        if not filename:
            return
        try:
            theme = install_theme_file(filename)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self._t("Thème", "Theme"), str(exc))
            return
        self._theme_path = str(theme.source_path or "")
        self.theme_name_label.setText(theme.name)
        self.settings.setValue("theme/path", self._theme_path)
        self.settings.setValue("theme/name", theme.name)
        self.settings.sync()
        self.settings_changed.emit()

    def _reset_theme(self) -> None:
        remove_installed_theme()
        self._theme_path = ""
        self.theme_name_label.setText(self._t("Thème d’origine", "Default theme"))
        self.settings.remove("theme/path")
        self.settings.setValue("theme/name", self._t("Thème d’origine", "Default theme"))
        self.settings.sync()
        self.settings_changed.emit()

    def _choose_game_log(self) -> None:
        initial = self._game_log_path or os.path.expandvars(
            r"%ProgramFiles%\Roberts Space Industries\StarCitizen\LIVE\Game.log"
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            self._t("Choisir le Game.log de Star Citizen", "Choose the Star Citizen Game.log"),
            initial,
            self._t("Game.log (Game.log);;Fichiers log (*.log);;Tous les fichiers (*)", "Game.log (Game.log);;Log files (*.log);;All files (*)"),
        )
        if not filename:
            return
        self._game_log_path = filename
        self.game_log_path_label.setText(filename)

    def set_game_log_status(self, status: str) -> None:
        self.game_log_status.setText(str(status or self._t("En attente de Game.log", "Waiting for Game.log")))

    def _update_test_device(self) -> None:
        self.audio_test.set_output_device(str(self.output_device.currentData() or ""))

    def _test_output(self) -> None:
        self._update_test_device()
        self.audio_test.set_volume(self.volume.value())
        self.audio_test.test_output()
        self.audio_status.setText(self._t("Test local lancé : un son bref doit être audible.", "Local test started: a short sound should be audible."))

    def selected_station(self):
        station_id = str(self.station.currentData() or DEFAULT_STATION_ID)
        return STATION_BY_ID.get(station_id, STATION_BY_ID[DEFAULT_STATION_ID])

    def _station_selection_changed(self) -> None:
        station = self.selected_station()
        self.test_radio_button.setText(f"{self._t('Tester', 'Test')} {station.name}")
        if self.audio_test.state in {"playing", "connecting"}:
            self.audio_test.play(station.stream_candidates)

    def _test_radio(self) -> None:
        self._update_test_device()
        self.audio_test.set_volume(self.volume.value())
        self.audio_test.play(self.selected_station().stream_candidates)

    def _audio_state_changed(self, state: str) -> None:
        station = self.selected_station()
        labels = {
            "connecting": self._t(f"Connexion audio à {station.name}…", f"Connecting audio to {station.name}…"),
            "playing": self._t(f"Audio connecté · {station.name}. Recherche du titre en cours…", f"Audio connected · {station.name}. Looking for track metadata…"),
            "paused": self._t("Test radio en pause.", "Radio test paused."),
            "stopped": self._t("Test arrêté.", "Test stopped."),
            "error": self._t(f"Le flux audio de {station.name} n'a pas répondu.", f"The {station.name} audio stream did not respond."),
        }
        self.audio_status.setText(labels.get(state, state))

    def _metadata_status_changed(self, state: str) -> None:
        labels = {
            "connecting": self._t("Audio actif · connexion au flux des titres radio…", "Audio active · connecting to the radio title stream…"),
            "connected": self._t("Audio et métadonnées radio connectés · titre en attente de diffusion.", "Radio audio and metadata connected · waiting for a track title."),
            "title": self._t("Audio et métadonnées radio connectés.", "Radio audio and metadata connected."),
            "unavailable": self._t("Audio actif · la radio ne diffuse pas de titre pour le moment.", "Audio active · the radio is not providing a track title right now."),
            "stopped": self._t("Métadonnées arrêtées.", "Metadata stopped."),
        }
        if state in labels:
            self.audio_status.setText(labels[state])

    def _update_location_mode_controls(self, _checked: bool | None = None) -> None:
        # The two checkboxes form one exclusive choice. Keep a valid mode even
        # when settings are changed programmatically.
        if not self.auto_game_location.isChecked() and not self.use_default_location.isChecked():
            self.auto_game_location.setChecked(True)
        self.location.setEnabled(self.use_default_location.isChecked())

    def save(self) -> None:
        self.settings.setValue("app/language", str(self.language.currentData() or "fr"))
        self.settings.setValue("widget/variant", "widget")
        self.settings.setValue("widget/auto_enabled", self.auto_widget.isChecked())
        self.settings.setValue("widget/auto_delay_seconds", self.auto_delay.value())
        self.settings.remove("widget/minimal_delay_seconds")
        self.settings.setValue("widget/remember_mode", self.start_widget.isChecked())
        self.settings.setValue("widget/always_on_top", self.always_on_top.isChecked())
        self.settings.setValue(
            "widget/auto_hide_game_ui_enabled", self.auto_hide_game_ui.isChecked()
        )
        self.settings.setValue(
            "widget/hide_in_inventory_enabled", self.hide_in_inventory.isChecked()
        )
        self.settings.setValue("widget/background_opacity", self.opacity.value())
        self.settings.setValue(HUD_COLOR_SETTINGS_KEY, normalize_hud_color(self._hud_color))
        self.settings.setValue(
            HUD_SECONDARY_COLOR_SETTINGS_KEY,
            normalize_hud_secondary_color(self._hud_secondary_color),
        )
        self.settings.remove("widget/window_opacity")
        self.settings.remove("widget/automatic_hud_color")
        self.settings.remove("widget/vehicle_hud_color_enabled")
        if self._theme_path:
            try:
                theme = load_theme_file(self._theme_path)
                self.settings.setValue("theme/path", self._theme_path)
                self.settings.setValue("theme/name", theme.name)
            except ValueError:
                self.settings.remove("theme/path")
                self.settings.setValue("theme/name", self._t("Thème d’origine", "Default theme"))
        else:
            self.settings.remove("theme/path")
            self.settings.setValue("theme/name", self._t("Thème d’origine", "Default theme"))
        self.settings.setValue("browser/keep_sessions", self.keep_sessions.isChecked())
        self.settings.setValue("browser/auto_fill_credentials", self.auto_fill_credentials.isChecked())
        selected_location = normalize_location_id(str(self.location.currentData() or "new-babbage"))
        automatic_location = self.auto_game_location.isChecked()
        if not automatic_location and not self.use_default_location.isChecked():
            self.use_default_location.setChecked(True)
        self.settings.setValue("verse_time/location", selected_location)
        self.settings.setValue("verse_weather/location", selected_location)
        self.settings.setValue(
            "game_log/location_mode", "automatic" if automatic_location else "default_city"
        )
        self.settings.setValue("game_log/auto_location_enabled", automatic_location)
        self.settings.remove("game_log/manual_override_pending")
        self.settings.remove("game_log/location_test_recording_enabled")
        if self._game_log_path:
            self.settings.setValue("game_log/path", self._game_log_path)
        else:
            self.settings.remove("game_log/path")
        self.settings.setValue("radio/station", str(self.station.currentData() or DEFAULT_STATION_ID))
        self.settings.setValue("radio/volume", self.volume.value())
        self.settings.setValue("radio/output_device", str(self.output_device.currentData() or ""))
        self.settings.remove("radio/streams")
        self.settings.remove("assistant")
        self.settings.setValue("app/start_with_windows", self.start_with_windows.isChecked())
        self.settings.sync()
        self._apply_windows_startup(self.start_with_windows.isChecked())
        self.settings_changed.emit()

    @staticmethod
    def _apply_windows_startup(enabled: bool) -> None:
        if os.name != "nt":
            return
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            launcher = os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "PublicRealTimeChecker", "Public_Real_Time_Checker.vbs"
            )
            command = f'wscript.exe "{launcher}"'
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, "PublicRealTimeChecker", 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, "PublicRealTimeChecker")
                    except FileNotFoundError:
                        pass
        except OSError:
            pass

    def shutdown(self) -> None:
        self.audio_test.shutdown()
