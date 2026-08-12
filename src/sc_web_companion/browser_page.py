from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QSettings, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .browser_profile import configure_web_profile
from .credential_vault import CredentialVault


def normalize_url(value: str) -> QUrl:
    value = value.strip()
    if not value:
        return QUrl()
    if "://" not in value:
        value = f"https://{value}"
    return QUrl.fromUserInput(value)


def origin_for_url(url: QUrl) -> str:
    if not url.isValid() or not url.host():
        return ""
    default_port = 443 if url.scheme() == "https" else 80
    port = url.port(default_port)
    suffix = "" if port == default_port else f":{port}"
    return f"{url.scheme()}://{url.host()}{suffix}".lower()


class EmbeddedWebView(QWebEngineView):
    """Web view whose pop-ups become sub-tabs instead of separate windows."""

    def __init__(
        self,
        parent: QWidget | None = None,
        profile: QWebEngineProfile | None = None,
        open_new_tab: Callable[[QUrl], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._open_new_tab = open_new_tab
        self._pending_popup_views: list[QWebEngineView] = []
        if profile is not None:
            self.setPage(QWebEnginePage(profile, self))

    def createWindow(self, window_type):  # noqa: N802 - Qt API naming
        del window_type
        popup = QWebEngineView(self)
        popup.setPage(QWebEnginePage(self.page().profile(), popup))
        self._pending_popup_views.append(popup)

        def redirect(url: QUrl, source: QWebEngineView = popup) -> None:
            if url.isValid() and not url.isEmpty():
                if self._open_new_tab is not None:
                    self._open_new_tab(url)
                else:
                    self.setUrl(url)
            try:
                self._pending_popup_views.remove(source)
            except ValueError:
                pass
            source.deleteLater()

        popup.urlChanged.connect(redirect)
        return popup


class CredentialDialog(QDialog):
    def __init__(
        self,
        origin: str,
        username: str = "",
        password: str = "",
        has_saved: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compte du site")
        self.username = QLineEdit(username)
        self.password = QLineEdit(password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setClearButtonEnabled(True)
        self.save_box = QCheckBox("Enregistrer dans le coffre sécurisé Windows")
        self.save_box.setChecked(True)
        note = QLabel(
            "Le mot de passe est chiffré par Windows pour votre session utilisateur. "
            "Il n'est ni synchronisé ni envoyé à Public Real Time Checker."
        )
        note.setWordWrap(True)
        note.setObjectName("homeSubtitle")
        form = QFormLayout()
        form.addRow("Site", QLabel(origin))
        form.addRow("Identifiant", self.username)
        form.addRow("Mot de passe", self.password)
        form.addRow(self.save_box)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Mettre à jour et remplir" if has_saved else "Enregistrer et remplir"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(440, 220)


class BrowserTab(QWidget):
    title_changed = Signal(str)
    url_changed = Signal(QUrl)

    def __init__(
        self,
        name: str,
        url: QUrl,
        profile: QWebEngineProfile,
        open_new_tab: Callable[[QUrl], None],
        force_dark: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.force_dark = bool(force_dark)
        self.browser = EmbeddedWebView(self, profile, open_new_tab)
        force_dark_attribute = getattr(QWebEngineSettings.WebAttribute, "ForceDarkMode", None)
        if self.force_dark and force_dark_attribute is not None:
            self.browser.settings().setAttribute(force_dark_attribute, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.browser.titleChanged.connect(lambda title: self.title_changed.emit(title or self.name))
        self.browser.urlChanged.connect(self.url_changed)
        self.browser.setUrl(url)


class BrowserPage(QWidget):
    """One sidebar section containing a complete set of browser sub-tabs."""

    title_changed = Signal(str)

    def __init__(
        self,
        name: str,
        home_url: str,
        parent: QWidget | None = None,
        force_dark: bool = False,
        settings: QSettings | None = None,
        profile: QWebEngineProfile | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.home_url = QUrl(home_url)
        self.force_dark = bool(force_dark)
        self.settings = settings
        self.profile = profile or configure_web_profile(settings)
        self.vault = CredentialVault()

        self.back_button = QPushButton("<")
        self.back_button.setToolTip("Page précédente")
        self.forward_button = QPushButton(">")
        self.forward_button.setToolTip("Page suivante")
        self.reload_button = QPushButton("Actualiser")
        self.home_button = QPushButton("Accueil du site")
        self.account_button = QPushButton("Compte")
        self.account_button.setToolTip(
            "Remplir ou enregistrer les identifiants de ce site dans le coffre Windows"
        )
        self.external_button = QPushButton("Ouvrir dehors")

        self.address = QLineEdit()
        self.address.setPlaceholderText("Adresse du site")
        self.address.setClearButtonEnabled(True)
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(3)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.status = QLabel("Prêt")
        self.status.setObjectName("browserStatus")

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._current_tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.new_tab_button = QPushButton("+")
        self.new_tab_button.setObjectName("smallButton")
        self.new_tab_button.setToolTip("Nouvel onglet dans cette section")
        self.new_tab_button.clicked.connect(lambda: self.add_tab(self.home_url))
        self.tabs.setCornerWidget(self.new_tab_button)

        navigation = QHBoxLayout()
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.setSpacing(6)
        for button in (self.back_button, self.forward_button, self.reload_button, self.home_button):
            navigation.addWidget(button)
        navigation.addWidget(self.address, 1)
        navigation.addWidget(self.account_button)
        navigation.addWidget(self.external_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(navigation)
        layout.addWidget(self.progress)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status)

        self.back_button.clicked.connect(lambda: self.browser.back())
        self.forward_button.clicked.connect(lambda: self.browser.forward())
        self.reload_button.clicked.connect(lambda: self.browser.reload())
        self.home_button.clicked.connect(lambda: self.browser.setUrl(self.home_url))
        self.account_button.clicked.connect(self.manage_credentials)
        self.external_button.clicked.connect(self.open_external)
        self.address.returnPressed.connect(self.navigate_from_address)

        self._shortcuts: list[QShortcut] = []
        self.add_shortcut("Ctrl+L", self.focus_address)
        self.add_shortcut("Ctrl+R", lambda: self.browser.reload())
        self.add_shortcut("Ctrl+T", lambda: self.add_tab(self.home_url))
        self.add_shortcut("Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex()))
        self.add_shortcut("Alt+Left", lambda: self.browser.back())
        self.add_shortcut("Alt+Right", lambda: self.browser.forward())
        self.add_tab(self.home_url, self.name)

    @property
    def current_tab(self) -> BrowserTab:
        widget = self.tabs.currentWidget()
        if not isinstance(widget, BrowserTab):
            raise RuntimeError("Aucun sous-onglet web actif.")
        return widget

    @property
    def browser(self) -> EmbeddedWebView:
        return self.current_tab.browser

    def add_tab(self, url: QUrl | str | None = None, title: str | None = None) -> BrowserTab:
        target = normalize_url(url) if isinstance(url, str) else (url or self.home_url)
        tab = BrowserTab(
            self.name,
            target,
            self.profile,
            self.add_tab,
            force_dark=self.force_dark,
            parent=self.tabs,
        )
        index = self.tabs.addTab(tab, title or "Nouvel onglet")
        tab.title_changed.connect(lambda text, page=tab: self._set_tab_title(page, text))
        tab.title_changed.connect(self.title_changed)
        tab.url_changed.connect(lambda changed, page=tab: self._tab_url_changed(page, changed))
        tab.browser.loadStarted.connect(self.on_load_started)
        tab.browser.loadProgress.connect(self.on_load_progress)
        tab.browser.loadFinished.connect(lambda ok, page=tab: self.on_load_finished(page, ok))
        self.tabs.setCurrentIndex(index)
        return tab

    def close_tab(self, index: int) -> None:
        if self.tabs.count() <= 1:
            self.browser.setUrl(self.home_url)
            return
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

    def _set_tab_title(self, tab: BrowserTab, title: str) -> None:
        index = self.tabs.indexOf(tab)
        if index >= 0:
            compact = " ".join(str(title or self.name).split())
            self.tabs.setTabText(index, compact[:32] + ("…" if len(compact) > 32 else ""))
            self.tabs.setTabToolTip(index, compact)

    def _tab_url_changed(self, tab: BrowserTab, url: QUrl) -> None:
        if tab is self.tabs.currentWidget():
            self.address.setText(url.toString())
            self._refresh_navigation()

    def _current_tab_changed(self, _index: int) -> None:
        if self.tabs.count() == 0:
            return
        self.address.setText(self.browser.url().toString())
        self._refresh_navigation()
        self.title_changed.emit(self.current_tab.browser.title() or self.name)

    def _refresh_navigation(self) -> None:
        history = self.browser.history()
        self.back_button.setEnabled(history.canGoBack())
        self.forward_button.setEnabled(history.canGoForward())

    def add_shortcut(self, sequence: str, callback: Callable[[], None]) -> None:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)

    def focus_address(self) -> None:
        self.address.setFocus()
        self.address.selectAll()

    def navigate_from_address(self) -> None:
        url = normalize_url(self.address.text())
        if url.isValid() and not url.isEmpty():
            self.browser.setUrl(url)

    def open_external(self) -> None:
        url = self.browser.url()
        if url.isValid():
            QDesktopServices.openUrl(url)

    def on_load_started(self) -> None:
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("Chargement...")

    def on_load_progress(self, value: int) -> None:
        self.progress.setValue(value)

    def on_load_finished(self, tab: BrowserTab, ok: bool) -> None:
        if tab is self.tabs.currentWidget():
            self.progress.hide()
            self.status.setText(
                "Page chargée" if ok else "Le site n'a pas répondu. Utilise Actualiser ou Ouvrir dehors."
            )
        if ok:
            self._autofill_saved_credential(tab)

    def _autofill_saved_credential(self, tab: BrowserTab) -> None:
        if self.settings is not None and not self.settings.value(
            "browser/auto_fill_credentials", True, type=bool
        ):
            return
        credential = self.vault.get(origin_for_url(tab.browser.url()))
        if credential is None:
            return
        script = self._fill_script(credential.username, credential.password)
        tab.browser.page().runJavaScript(script)

    @staticmethod
    def _fill_script(username: str, password: str) -> str:
        user_json = json.dumps(username)
        pass_json = json.dumps(password)
        return f"""
        (() => {{
          const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
          const password = [...document.querySelectorAll('input[type=password]')].find(visible);
          if (!password) return false;
          const form = password.form || document;
          const users = [...form.querySelectorAll('input[type=email],input[type=text],input:not([type])')]
            .filter(visible).filter(el => !el.disabled && !el.readOnly);
          const user = users.find(el => /user|email|login|account|identifier/i.test(`${{el.name}} ${{el.id}} ${{el.autocomplete}}`)) || users[0];
          const set = (el, value) => {{
            if (!el) return;
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(el, value);
            el.dispatchEvent(new Event('input', {{bubbles:true}}));
            el.dispatchEvent(new Event('change', {{bubbles:true}}));
          }};
          set(user, {user_json}); set(password, {pass_json});
          return true;
        }})()
        """

    @staticmethod
    def _extract_script() -> str:
        return """
        (() => {
          const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
          const password = [...document.querySelectorAll('input[type=password]')].find(visible);
          if (!password) return {username:'', password:''};
          const form = password.form || document;
          const users = [...form.querySelectorAll('input[type=email],input[type=text],input:not([type])')]
            .filter(visible).filter(el => !el.disabled && !el.readOnly);
          const user = users.find(el => /user|email|login|account|identifier/i.test(`${el.name} ${el.id} ${el.autocomplete}`)) || users[0];
          return {username: user ? user.value : '', password: password.value || ''};
        })()
        """

    def manage_credentials(self) -> None:
        if not self.vault.available:
            QMessageBox.information(
                self,
                "Coffre Windows",
                "Le coffre chiffré est disponible dans la version Windows installée.",
            )
            return
        origin = origin_for_url(self.browser.url())
        if not origin:
            QMessageBox.information(self, "Compte du site", "Cette page n'a pas d'adresse de site valide.")
            return
        saved = self.vault.get(origin)

        def show_dialog(fields: object) -> None:
            values = fields if isinstance(fields, dict) else {}
            dialog = CredentialDialog(
                origin,
                (saved.username if saved else str(values.get("username", ""))),
                (saved.password if saved else str(values.get("password", ""))),
                bool(saved),
                self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            username = dialog.username.text().strip()
            password = dialog.password.text()
            if not password:
                QMessageBox.warning(self, "Compte du site", "Aucun mot de passe à remplir.")
                return
            if dialog.save_box.isChecked():
                self.vault.save(origin, username, password)
            self.browser.page().runJavaScript(self._fill_script(username, password))
            self.status.setText("Identifiants remplis. Le site reste responsable de la connexion.")

        self.browser.page().runJavaScript(self._extract_script(), show_dialog)

    def serialize_tabs(self) -> list[str]:
        result: list[str] = []
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if isinstance(tab, BrowserTab):
                url = tab.browser.url().toString()
                if url:
                    result.append(url)
        return result or [self.home_url.toString()]

    def restore_tabs(self, urls: list[str]) -> None:
        cleaned = [url for url in urls if normalize_url(str(url)).isValid()]
        if not cleaned:
            return
        while self.tabs.count() > 0:
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        for url in cleaned[:12]:
            self.add_tab(url)

    def shutdown(self) -> None:
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if isinstance(tab, BrowserTab):
                tab.browser.stop()
