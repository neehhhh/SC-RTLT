from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QEvent, QSettings, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .browser_page import BrowserPage, normalize_url
from .browser_profile import clear_browser_data, configure_web_profile
from .config import SiteDefinition, add_custom_site, config_directory, load_sites, remove_custom_site
from .controls import AppleSwitch
from .companion_widget import (
    SpaceTheme,
    set_custom_space_themes,
    set_custom_widget_visual_style,
)
from .credential_vault import CredentialVault
from .game_log_location import GameLogLocationMonitor
from .game_ui_state import GameUiStateMonitor, should_hide_widget_for_game_ui
from .hud_layout_editor import HudLayoutEditor
from .language import current_language, site_description, site_name, tr
from .radio_hotkeys import RadioHotkeyManager
from .radio_page import DEFAULT_STATION_ID, STATION_BY_ID
from .settings_page import SettingsPage
from .styles import APP_STYLE
from .theme_loader import load_theme_file
from .widget_window import WidgetWindow
from .verse_time import normalize_location_id


CUSTOM_SITE_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class SidebarItemDelegate(QStyledItemDelegate):
    """Paint a remove control only for user-created sections."""

    remove_requested = Signal(str)

    @staticmethod
    def remove_rect(option: QStyleOptionViewItem):
        return option.rect.adjusted(max(0, option.rect.width() - 34), 2, -2, -2)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        custom = bool(index.data(CUSTOM_SITE_ROLE))
        text_option = QStyleOptionViewItem(option)
        if custom:
            text_option.rect = text_option.rect.adjusted(0, 0, -32, 0)
        super().paint(painter, text_option, index)
        if not custom:
            return
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QColor("#ffffff") if selected else QColor("#aeb8c2"))
        painter.drawText(self.remove_rect(option), Qt.AlignmentFlag.AlignCenter, "−")
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if (
            bool(index.data(CUSTOM_SITE_ROLE))
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.remove_rect(option).contains(event.position().toPoint())
        ):
            self.remove_requested.emit(str(index.data(Qt.ItemDataRole.UserRole)))
            return True
        return super().editorEvent(event, model, option, index)


class AddSiteDialog(QDialog):
    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr(settings, "Ajouter un site", "Add a website"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("Ex. FleetYards")
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://...")
        note = QLabel(
            tr(settings, "Le site sera ajouté à la barre latérale et bénéficiera des mêmes sous-onglets, sessions persistantes et contrôles de navigation.", "The website will be added to the sidebar with the same sub-tabs, persistent sessions and navigation controls.")
        )
        note.setWordWrap(True)
        note.setObjectName("homeSubtitle")
        form = QFormLayout()
        form.addRow(tr(settings, "Nom", "Name"), self.name)
        form.addRow(tr(settings, "Adresse", "Address"), self.url)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr(settings, "Ajouter", "Add"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(470, 190)

    def accept(self) -> None:
        if not self.name.text().strip() or not normalize_url(self.url.text()).isValid():
            QMessageBox.warning(self, tr(self.settings, "Ajouter un site", "Add a website"), tr(self.settings, "Indique un nom et une adresse web valide.", "Enter a name and a valid web address."))
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings(
            str(config_directory() / "settings.ini"), QSettings.Format.IniFormat
        )
        self.language = current_language(self.settings)
        self.web_profile = configure_web_profile(self.settings)
        self.credential_vault = CredentialVault()
        self.sites = load_sites()
        self.site_by_id = {site.site_id: site for site in self.sites}
        self.page_by_id: dict[str, QWidget] = {}
        self.item_by_id: dict[str, QListWidgetItem] = {}
        self._normal_geometry: QByteArray | None = None
        self._widget_geometry: QByteArray | None = None
        self._normal_page_id = "news"
        self._widget_mode = False
        self._quitting = False
        self._last_real_page_id = "news"

        self.setWindowTitle("Public Real Time Checker")
        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        self.setMinimumSize(900, 620)
        self.resize(1360, 850)
        self._apply_loaded_theme()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowOpacity(1.0)
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            self.settings.value("widget/always_on_top", True, type=bool),
        )

        self.sidebar = QListWidget()
        self.sidebar.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.sidebar.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.sidebar.setDragEnabled(True)
        self.sidebar.setAcceptDrops(True)
        self.sidebar.setDropIndicatorShown(True)
        self.sidebar_delegate = SidebarItemDelegate(self.sidebar)
        self.sidebar_delegate.remove_requested.connect(self.delete_custom_site)
        self.sidebar.setItemDelegate(self.sidebar_delegate)
        self.sidebar.currentItemChanged.connect(self.on_navigation_changed)
        self.sidebar.model().rowsMoved.connect(self._save_navigation_order)
        self.add_site_button = QPushButton(tr(self.settings, "+  Ajouter un site", "+  Add website"))
        self.add_site_button.setObjectName("sidebarAddButton")
        self.add_site_button.setToolTip(tr(self.settings, "Créer une section web depuis une adresse", "Create a web section from an address"))
        self.add_site_button.clicked.connect(self.open_add_site_dialog)
        self.sidebar_shell = QWidget()
        self.sidebar_shell.setObjectName("sidebarShell")
        self.sidebar_shell.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(self.sidebar_shell)
        sidebar_layout.setContentsMargins(0, 0, 0, 8)
        sidebar_layout.setSpacing(4)
        sidebar_layout.addWidget(self.sidebar, 1)
        sidebar_layout.addWidget(self.add_site_button, 0)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")

        self.header_widget_label = QLabel(tr(self.settings, "Widget", "Widget"))
        self.header_widget_label.setObjectName("headerWidgetLabel")
        self.header_switch = AppleSwitch()
        self.header_switch.setChecked(False)
        self.header_switch.toggled.connect(self.set_widget_mode)
        self.app_title = QLabel("Public Real Time Checker")
        self.app_title.setObjectName("appTitle")
        self.app_subtitle = QLabel(tr(self.settings, "Outils web, radio et widget Star Citizen", "Star Citizen web tools, radio and widget"))
        self.app_subtitle.setObjectName("appSubtitle")

        self.header = QWidget()
        self.header.setObjectName("header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(14, 9, 14, 9)
        header_layout.setSpacing(7)
        header_layout.addWidget(self.app_title)
        header_layout.addWidget(self.app_subtitle)
        header_layout.addStretch(1)
        header_layout.addWidget(self.header_widget_label)
        header_layout.addWidget(self.header_switch)

        body = QWidget()
        body.setObjectName("bodyShell")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.sidebar_shell)
        body_layout.addWidget(self.stack, 1)

        central = QWidget()
        central.setObjectName("centralShell")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.header)
        central_layout.addWidget(body, 1)
        self.setCentralWidget(central)

        self.widget_window = WidgetWindow(self.settings)
        self.widget_page = self.widget_window.page
        self.widget_window.restore_requested.connect(lambda: self.set_widget_mode(False))
        self.widget_window.close_app_requested.connect(self.quit_from_widget)
        self.widget_window.settings_requested.connect(self.open_settings)
        self.widget_page.location_capture_requested.connect(self._capture_test_location)

        self.radio_hotkeys = RadioHotkeyManager(self)
        self.radio_hotkeys.minimal_widget_requested.connect(self.minimize_widget_hotkey)
        self.radio_hotkeys.widget_requested.connect(self.open_widget_hotkey)
        self.radio_hotkeys.previous_requested.connect(lambda: self.widget_page.change_station(-1))
        self.radio_hotkeys.play_pause_requested.connect(self.widget_page.toggle_playback)
        self.radio_hotkeys.next_requested.connect(lambda: self.widget_page.change_station(1))

        self.auto_widget_timer = QTimer(self)
        self.auto_widget_timer.setSingleShot(True)
        self.auto_widget_timer.timeout.connect(lambda: self.set_widget_mode(True))
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.build_navigation()
        self.build_actions()
        self.retranslate_ui()
        self.game_log_monitor = GameLogLocationMonitor(self.settings, self)
        self.game_log_monitor.location_changed.connect(self._on_game_location_changed)
        self.game_log_monitor.status_changed.connect(self._on_game_log_status_changed)
        self.game_log_monitor.start()
        self.game_ui_monitor = GameUiStateMonitor(self.settings, self)
        self.game_ui_monitor.ui_active_changed.connect(self._on_game_ui_state_changed)
        self.game_ui_monitor.location_refresh_requested.connect(
            self._on_location_refresh_requested
        )
        self.game_ui_monitor.quantum_commit_requested.connect(
            self._on_quantum_commit_requested
        )
        self.game_ui_monitor.start()
        self.restore_saved_state()


    def _localized_game_log_status(self, status: str) -> str:
        text = str(status or "")
        if self.language != "en":
            return text
        replacements = {
            "Lieu détecté :": "Location detected:",
            "En attente de Game.log": "Waiting for Game.log",
            "Game.log introuvable": "Game.log not found",
            "Surveillance de Game.log active": "Game.log monitoring active",
        }
        for french, english in replacements.items():
            if text.startswith(french):
                return english + text[len(french):]
        return text

    def _connect_settings_page(self, page: SettingsPage) -> None:
        page.settings_changed.connect(self.apply_settings)
        page.reset_widget_geometry_requested.connect(self.reset_widget_geometry)
        page.edit_hud_layout_requested.connect(self.open_hud_layout_editor)
        page.clear_browser_data_requested.connect(self.clear_browser_profile)
        page.clear_credentials_requested.connect(self.clear_credentials)

    def _rebuild_settings_page(self) -> None:
        old_page = getattr(self, "settings_page", None)
        if old_page is None:
            return
        was_current = self.stack.currentWidget() is old_page
        index = self.stack.indexOf(old_page)
        shutdown = getattr(old_page, "shutdown", None)
        if callable(shutdown):
            shutdown()
        self.stack.removeWidget(old_page)
        old_page.deleteLater()
        page = SettingsPage(self.settings)
        self._connect_settings_page(page)
        self.stack.insertWidget(max(0, index), page)
        self.page_by_id["settings"] = page
        self.settings_page = page
        if was_current:
            self.stack.setCurrentWidget(page)

    def retranslate_ui(self) -> None:
        self.language = current_language(self.settings)
        self.add_site_button.setText(tr(self.settings, "+  Ajouter un site", "+  Add website"))
        self.add_site_button.setToolTip(tr(self.settings, "Créer une section web depuis une adresse", "Create a web section from an address"))
        self.header_widget_label.setText(tr(self.settings, "Widget", "Widget"))
        self.app_subtitle.setText(tr(self.settings, "Outils web, radio et widget Star Citizen", "Star Citizen web tools, radio and widget"))
        if hasattr(self, "widget_action"):
            self.widget_action.setText(tr(self.settings, "Basculer le mode widget", "Toggle widget mode"))
        if hasattr(self, "settings_action"):
            self.settings_action.setText(tr(self.settings, "Réglages", "Settings"))
        settings_item = self.item_by_id.get("settings")
        if settings_item is not None:
            settings_item.setText(tr(self.settings, "Réglage", "Settings"))
            settings_item.setToolTip(tr(self.settings, "Widget, navigation, comptes et sortie audio", "Widget, navigation, accounts and audio output"))
        for site in self.sites:
            item = self.item_by_id.get(site.site_id)
            if item is None:
                continue
            item.setText(site_name(site.site_id, site.name, self.language))
            description = site_description(site.site_id, site.description, self.language)
            if description:
                item.setToolTip(description + (("\n" + tr(self.settings, "Cliquer sur − pour supprimer.", "Click − to remove.")) if site.custom else ""))

    @staticmethod
    def _space_theme_from_palette(palette) -> SpaceTheme | None:
        if palette is None:
            return None
        return SpaceTheme(
            palette.accent,
            palette.highlight,
            palette.deep,
            palette.effect,
            palette.planet_x,
            palette.planet_y,
            palette.planet_radius,
        )

    def _apply_loaded_theme(self) -> None:
        path = self.settings.value("theme/path", "", type=str).strip()
        try:
            theme = load_theme_file(path)
        except ValueError:
            self.settings.remove("theme/path")
            self.settings.setValue("theme/name", tr(self.settings, "Thème d’origine", "Default theme"))
            theme = load_theme_file(None)
        default_theme = self._space_theme_from_palette(theme.default_palette)
        location_themes = {
            key: self._space_theme_from_palette(palette)
            for key, palette in theme.location_palettes.items()
        }
        set_custom_space_themes(
            default_theme,
            {key: value for key, value in location_themes.items() if value is not None},
        )
        set_custom_widget_visual_style(theme.widget_visual)
        custom_qss = theme.app_qss.strip()
        self.setStyleSheet(
            APP_STYLE + ("\n/* Thème chargé */\n" + custom_qss if custom_qss else "")
        )
        self.settings.setValue("theme/name", theme.name)
        self.settings.sync()
        widget_window = getattr(self, "widget_window", None)
        if widget_window is not None:
            widget_window.refresh_theme()

    def _on_game_location_changed(self, name: str, body: str, raw_location: str) -> None:
        self.widget_page.set_detected_location(name, body, raw_location)
        self.settings_page.set_game_log_status(tr(self.settings, f"Lieu détecté : {name} · {body}", f"Location detected: {name} · {body}"))

    def _on_game_vehicle_changed(
        self, manufacturer_id: str, vehicle_code: str
    ) -> None:
        self.widget_page.set_detected_vehicle(manufacturer_id, vehicle_code)

    def _on_game_log_status_changed(self, status: str) -> None:
        self.settings_page.set_game_log_status(self._localized_game_log_status(status))

    def _capture_test_location(self) -> None:
        label, accepted = QInputDialog.getText(
            self,
            tr(self.settings, "Capture Public Real Time Checker", "Public Real Time Checker capture"),
            tr(self.settings, "Où suis-je réellement ?", "Where am I actually?"),
        )
        if not accepted or not label.strip():
            return
        result = self.game_log_monitor.confirm_test_location(label.strip())
        if not bool(result.get("saved")):
            reason = str(result.get("reason") or "")
            if reason == "no_recent_location_code":
                QMessageBox.warning(
                    self,
                    tr(self.settings, "Public Real Time Checker", "Public Real Time Checker"),
                    tr(
                        self.settings,
                        "Aucun code de localisation fiable n'a encore été trouvé dans Game.log. Ouvrez l'inventaire ou changez légèrement de zone, puis recommencez.",
                        "No reliable location code has been found in Game.log yet. Open the inventory or move slightly, then try again.",
                    ),
                )
            else:
                QMessageBox.critical(
                    self,
                    tr(self.settings, "Public Real Time Checker", "Public Real Time Checker"),
                    tr(
                        self.settings,
                        "Le fichier Public Real Time Checker n'a pas pu être écrit.",
                        "The Public Real Time Checker file could not be written.",
                    ),
                )
            return
        code = str(result.get("location_code") or "")
        output_path = str(
            result.get("output_path") or self.game_log_monitor.public_parser_output_file
        )
        self.widget_page.card.setToolTip(
            f"{tr(self.settings, 'Capture enregistrée', 'Capture saved')} : {label.strip()}\n"
            f"{tr(self.settings, 'Code', 'Code')} : {code}\n"
            f"{tr(self.settings, 'Fichier', 'File')} : {output_path}"
        )

    def _on_location_refresh_requested(self, reason: str) -> None:
        if not hasattr(self, "game_log_monitor"):
            return
        reason = str(reason or "")
        if reason == "f2":
            # F2 toggles the Starmap. When a preview is visible it closes the map
            # and restores the separate physical snapshot; otherwise it starts a
            # fresh map session so delayed events from the previous map are ignored.
            if self.game_log_monitor.map_session_open:
                self.game_log_monitor.force_current_position()
            else:
                self.game_log_monitor.begin_map_session()
            return
        if reason == "ui_closed":
            self.game_log_monitor.restore_after_map_close()
            return
        # Escape explicitly closes any Starmap preview and restores physical state.
        self.game_log_monitor.force_current_position()

    def _on_quantum_commit_requested(self) -> None:
        if hasattr(self, "game_log_monitor"):
            self.game_log_monitor.commit_quantum_destination()

    def _on_game_ui_state_changed(self, active: bool, reason: str) -> None:
        if self._quitting:
            self.widget_window.set_inventory_compact(False)
            self.widget_window.set_game_ui_suppressed(False, restore=False)
            return
        if not self._widget_mode:
            self.widget_window.set_inventory_compact(False)
            self.widget_window.set_game_ui_suppressed(False, restore=False)
            return
        # Inventory must hide the full widget exactly like the other interactive
        # game interfaces. Never collapse the normal widget into mini mode here.
        self.widget_window.set_inventory_compact(False)
        self.widget_window.set_game_ui_suppressed(
            should_hide_widget_for_game_ui(active, reason)
        )

    def add_navigation_item(
        self, page_id: str, label: str, tooltip: str = "", *, custom: bool = False, row: int | None = None
    ) -> QListWidgetItem:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, page_id)
        item.setData(CUSTOM_SITE_ROLE, bool(custom))
        if tooltip:
            item.setToolTip(tooltip + (("\n" + tr(self.settings, "Cliquer sur − pour supprimer.", "Click − to remove.")) if custom else ""))
        if row is None:
            self.sidebar.addItem(item)
        else:
            self.sidebar.insertItem(max(0, min(int(row), self.sidebar.count())), item)
        self.item_by_id[page_id] = item
        return item

    def _saved_navigation_order(self) -> list[str]:
        raw = self.settings.value("navigation/order", "", type=str)
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            return []
        return [str(page_id) for page_id in value] if isinstance(value, list) else []

    def _navigation_order(self) -> list[str]:
        return [
            str(self.sidebar.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.sidebar.count())
        ]

    def _save_navigation_order(self, *_args) -> None:
        if not hasattr(self, "settings") or not hasattr(self, "sidebar"):
            return
        self.settings.setValue("navigation/order", json.dumps(self._navigation_order()))
        self.settings.sync()

    def build_navigation(self) -> None:
        available = {site.site_id: site for site in self.sites}
        default_order = [site.site_id for site in self.sites] + ["settings"]
        saved = self._saved_navigation_order()
        ordered_ids = [page_id for page_id in saved if page_id in available or page_id == "settings"]
        ordered_ids.extend(page_id for page_id in default_order if page_id not in ordered_ids)
        for page_id in ordered_ids:
            if page_id == "settings":
                self.add_navigation_item(
                    "settings",
                    tr(self.settings, "Réglage", "Settings"),
                    tr(self.settings, "Widget, navigation, comptes et sortie audio", "Widget, navigation, accounts and audio output"),
                )
                continue
            site = available[page_id]
            self.add_navigation_item(
                site.site_id,
                site_name(site.site_id, site.name, self.language),
                site_description(site.site_id, site.description, self.language),
                custom=site.custom,
            )

        settings_page = SettingsPage(self.settings)
        self._connect_settings_page(settings_page)
        self.stack.addWidget(settings_page)
        self.page_by_id["settings"] = settings_page
        self.settings_page = settings_page
        self.sidebar.setCurrentItem(self.item_by_id["news"])

    def build_actions(self) -> None:
        self.widget_action = QAction(tr(self.settings, "Basculer le mode widget", "Toggle widget mode"), self)
        self.widget_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        self.widget_action.triggered.connect(self.toggle_widget_mode)
        self.addAction(self.widget_action)
        self.settings_action = QAction(tr(self.settings, "Réglages", "Settings"), self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self.open_settings)
        self.addAction(self.settings_action)

    def current_page_id(self) -> str:
        current = self.sidebar.currentItem()
        return str(current.data(Qt.ItemDataRole.UserRole)) if current is not None else "news"

    def on_navigation_changed(self, current, previous) -> None:
        if current is None:
            return
        page_id = str(current.data(Qt.ItemDataRole.UserRole))
        self._last_real_page_id = page_id
        self.show_page(page_id)

    def open_add_site_dialog(self) -> None:
        dialog = AddSiteDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url = normalize_url(dialog.url.text()).toString()
        site = add_custom_site(dialog.name.text(), url)
        self.sites = load_sites()
        self.site_by_id[site.site_id] = site
        settings_item = self.item_by_id.get("settings")
        row = self.sidebar.row(settings_item) if settings_item is not None else self.sidebar.count()
        item = self.add_navigation_item(
            site.site_id, site.name, site.description, custom=True, row=row
        )
        self.sidebar.setCurrentItem(item)
        self.show_page(site.site_id)
        self._save_navigation_order()

    def delete_custom_site(self, site_id: str) -> bool:
        site = self.site_by_id.get(site_id)
        if site is None or not site.custom or not remove_custom_site(site_id):
            return False
        page = self.page_by_id.pop(site_id, None)
        if page is not None:
            self.stack.removeWidget(page)
            page.deleteLater()
        item = self.item_by_id.pop(site_id, None)
        if item is not None:
            self.sidebar.takeItem(self.sidebar.row(item))
        self.site_by_id.pop(site_id, None)
        self.sites = load_sites()
        self.select_site("news")
        self._save_navigation_order()
        return True

    def show_page(self, page_id: str) -> None:
        page = self.page_by_id.get(page_id)
        if page is None:
            site = self.site_by_id.get(page_id)
            if site is None:
                return
            page = self.create_browser_page(site)
            self.page_by_id[page_id] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def create_browser_page(self, site: SiteDefinition) -> BrowserPage:
        page = BrowserPage(
            site.name,
            site.url,
            force_dark=(site.site_id == "uex"),
            settings=self.settings,
            profile=self.web_profile,
        )
        page.title_changed.connect(
            lambda title, site_name=site.name: self.setWindowTitle(
                f"{title} - Public Real Time Checker" if title else f"{site_name} - Public Real Time Checker"
            )
        )
        raw = self.settings.value(f"browser/tabs/{site.site_id}", "", type=str)
        if raw:
            try:
                urls = json.loads(raw)
                if isinstance(urls, list):
                    page.restore_tabs([str(url) for url in urls])
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        return page

    def select_site(self, site_id: str) -> None:
        if self._widget_mode:
            self.set_widget_mode(False)
        item = self.item_by_id.get(site_id)
        if item is not None:
            self.sidebar.setCurrentItem(item)
            self.show_page(site_id)

    def open_settings(self) -> None:
        self.set_widget_mode(False)
        self.select_site("settings")

    def toggle_widget_mode(self) -> None:
        self.set_widget_mode(not self._widget_mode)

    def open_widget_hotkey(self) -> None:
        if not self._widget_mode:
            self.set_widget_mode(True)
        self.widget_window.reveal_expanded()

    def minimize_widget_hotkey(self) -> None:
        if not self._widget_mode:
            self.set_widget_mode(True)
        self.widget_window.force_minimal()

    def set_widget_mode(self, enabled: bool, restoring: bool = False) -> None:
        enabled = bool(enabled)
        if enabled == self._widget_mode and not restoring:
            return
        if enabled:
            self._normal_geometry = self.saveGeometry()
            self._normal_page_id = self.current_page_id()
            self._widget_mode = True
            self.auto_widget_timer.stop()
            self.hide()
            self.widget_window.show_widget(self._widget_geometry)
            monitor = getattr(self, "game_ui_monitor", None)
            if monitor is not None:
                self.widget_window.set_game_ui_suppressed(monitor.ui_active)
        else:
            self.widget_window.set_game_ui_suppressed(False, restore=False)
            if self._widget_mode:
                self._widget_geometry = self.widget_window.hide_widget()
            self._widget_mode = False
            self.setWindowOpacity(1.0)
            if self._normal_geometry:
                self.restoreGeometry(self._normal_geometry)
            self.show()
            self.raise_()
            self.activateWindow()
            if self._normal_page_id in self.item_by_id:
                self.sidebar.setCurrentItem(self.item_by_id[self._normal_page_id])
                self.show_page(self._normal_page_id)
            self.reset_auto_widget_timer()

        blocker = QSignalBlocker(self.header_switch)
        self.header_switch.setChecked(enabled)
        del blocker
        self.settings.setValue("window/widget_mode", enabled)
        self.settings.sync()

    def apply_settings(self) -> None:
        app_was_visible = self.isVisible() and not self._widget_mode
        language_changed = current_language(self.settings) != self.language
        if language_changed:
            self.language = current_language(self.settings)
            self._rebuild_settings_page()
        self.retranslate_ui()

        configure_web_profile(self.settings)
        self._apply_loaded_theme()
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            self.settings.value("widget/always_on_top", True, type=bool),
        )
        self.widget_window.apply_settings()
        self.game_log_monitor.reconfigure()
        self.game_ui_monitor.reconfigure()
        if self._widget_mode:
            self.widget_window.set_game_ui_suppressed(self.game_ui_monitor.ui_active)

        if app_was_visible:
            self.show()
            self.raise_()
            self.activateWindow()

        self.reset_auto_widget_timer()

    def open_hud_layout_editor(self) -> None:
        editor = getattr(self, "_hud_layout_editor", None)
        if editor is not None and editor.isVisible():
            editor.raise_()
            editor.activateWindow()
            return
        widget_was_visible = self.widget_window.isVisible()
        try:
            editor = HudLayoutEditor(
                self.settings, self.widget_page.set_hud_layout_preview, self
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                tr(self.settings, "Éditeur du HUD", "HUD editor"),
                tr(
                    self.settings,
                    "L’éditeur du HUD n’a pas pu s’ouvrir.",
                    "The HUD editor could not open.",
                )
                + f"\n\n{type(exc).__name__}: {exc}",
            )
            return

        def editor_finished(_result: int) -> None:
            self._hud_layout_editor = None
            if not widget_was_visible and not self._widget_mode:
                self.widget_window.hide_widget()

        editor.finished.connect(editor_finished)
        self._hud_layout_editor = editor
        if not widget_was_visible:
            self.widget_window.show_widget()
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def clear_browser_profile(self) -> None:
        clear_browser_data(self.web_profile)
        QMessageBox.information(
            self,
            tr(self.settings, "Données de navigation", "Browsing data"),
            tr(self.settings, "Les cookies, le cache et les liens visités ont été effacés. Les onglets ouverts restent disponibles.", "Cookies, cache and visited links were cleared. Open tabs remain available."),
        )

    def clear_credentials(self) -> None:
        self.credential_vault.clear()
        QMessageBox.information(self, tr(self.settings, "Coffre Windows", "Windows vault"), tr(self.settings, "Les identifiants enregistrés ont été supprimés.", "Saved credentials were removed."))

    def reset_widget_geometry(self) -> None:
        self._widget_geometry = None
        self.settings.remove("window/widget_geometry")
        self.settings.sync()
        self.widget_window.reset_geometry()

    def reset_auto_widget_timer(self) -> None:
        self.auto_widget_timer.stop()
        if self._widget_mode or not self.isVisible():
            return
        if not self.settings.value("widget/auto_enabled", True, type=bool):
            return
        delay = max(5, self.settings.value("widget/auto_delay_seconds", 30, type=int))
        self.auto_widget_timer.start(delay * 1000)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if self.isVisible() and not self._widget_mode and event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.KeyPress,
            QEvent.Type.Wheel,
            QEvent.Type.TouchBegin,
        }:
            self.reset_auto_widget_timer()
        return super().eventFilter(watched, event)

    def restore_saved_state(self) -> None:
        normal_geometry = self.settings.value("window/normal_geometry")
        self._normal_geometry = normal_geometry if isinstance(normal_geometry, QByteArray) else None
        if self._normal_geometry:
            self.restoreGeometry(self._normal_geometry)
        widget_geometry = self.settings.value("window/widget_geometry")
        self._widget_geometry = widget_geometry if isinstance(widget_geometry, QByteArray) else None
        self._normal_page_id = self.settings.value("window/normal_last_page", "news", type=str)
        if self._normal_page_id not in self.item_by_id:
            self._normal_page_id = "news"

        style_version = self.settings.value("widget/style_version", "", type=str)
        if style_version != "0.9.13-gamelog-location-test":
            self.settings.setValue("widget/style_version", "0.9.13-gamelog-location-test")
            old_location = self.settings.value("verse_weather/location", "new-babbage", type=str)
            current_location = self.settings.value("verse_time/location", "", type=str) or old_location
            normalized_location = normalize_location_id(current_location)
            self.settings.setValue("verse_time/location", normalized_location)
            self.settings.setValue("verse_weather/location", normalized_location)
            saved_station = self.settings.value("radio/station", DEFAULT_STATION_ID, type=str)
            if saved_station not in STATION_BY_ID:
                self.settings.setValue("radio/station", DEFAULT_STATION_ID)
            if self.settings.value("widget/variant", None) is None:
                self.settings.setValue("widget/variant", "widget")
            if self.settings.value("browser/keep_sessions", None) is None:
                self.settings.setValue("browser/keep_sessions", True)
            if self.settings.value("browser/auto_fill_credentials", None) is None:
                self.settings.setValue("browser/auto_fill_credentials", True)
            self.settings.remove("radio/streams")
            self.settings.remove("assistant")
            if self.settings.value("widget/background_opacity", None) is None:
                legacy_opacity = self.settings.value("widget/window_opacity", 100)
                try:
                    legacy_opacity = max(5, min(100, int(legacy_opacity)))
                except (TypeError, ValueError):
                    legacy_opacity = 100
                self.settings.setValue("widget/background_opacity", legacy_opacity)
            self.settings.remove("widget/window_opacity")
        self.settings.sync()
        self.widget_window.page.apply_external_settings()

        remember_mode = self.settings.value("widget/remember_mode", True, type=bool)
        start_widget = remember_mode and self.settings.value("window/widget_mode", False, type=bool)
        if start_widget:
            QTimer.singleShot(0, lambda: self.set_widget_mode(True, restoring=True))
        else:
            QTimer.singleShot(0, lambda: self.select_site(self._normal_page_id))
            QTimer.singleShot(0, self.reset_auto_widget_timer)

    def _save_state(self) -> None:
        if self._widget_mode:
            self._widget_geometry = self.widget_window.saveGeometry()
        else:
            self._normal_geometry = self.saveGeometry()
            self._normal_page_id = self.current_page_id()
        if self._normal_geometry:
            self.settings.setValue("window/normal_geometry", self._normal_geometry)
        if self._widget_geometry:
            self.settings.setValue("window/widget_geometry", self._widget_geometry)
        for page_id, page in self.page_by_id.items():
            if isinstance(page, BrowserPage):
                self.settings.setValue(
                    f"browser/tabs/{page_id}", json.dumps(page.serialize_tabs(), ensure_ascii=False)
                )
        self.settings.setValue("window/normal_last_page", self._normal_page_id)
        self.settings.setValue("window/widget_mode", self._widget_mode)
        self.settings.sync()

    def _shutdown_pages(self) -> None:
        seen: set[int] = set()
        for page in self.page_by_id.values():
            if id(page) in seen:
                continue
            seen.add(id(page))
            shutdown = getattr(page, "shutdown", None)
            if callable(shutdown):
                shutdown()

    def quit_from_widget(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._save_state()
        self.widget_window.hide()
        self.radio_hotkeys.shutdown()
        self.game_log_monitor.shutdown()
        self.game_ui_monitor.shutdown()
        self.widget_window.shutdown()
        self._shutdown_pages()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._quitting:
            event.accept()
            return
        self._quitting = True
        self._save_state()
        self.widget_window.hide()
        self.radio_hotkeys.shutdown()
        self.game_log_monitor.shutdown()
        self.game_ui_monitor.shutdown()
        self.widget_window.shutdown()
        self._shutdown_pages()
        event.accept()
