from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths
from PySide6.QtWebEngineCore import QWebEngineProfile

from .config import config_directory


_SHARED_PROFILE: QWebEngineProfile | None = None


def browser_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data) / "PublicRealTimeCheckerData"
    else:
        root = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    root.mkdir(parents=True, exist_ok=True)
    return root


def configure_web_profile(settings: QSettings | None = None) -> QWebEngineProfile:
    """Return the single persistent Chromium profile shared by every web tab.

    A named profile is created before the first page, rather than mutating Qt's
    global default profile after Chromium has started. This keeps cookies,
    localStorage and recognised accounts stable across all sidebar sections and
    application restarts.
    """
    global _SHARED_PROFILE
    settings = settings or QSettings(
        str(config_directory() / "settings.ini"), QSettings.Format.IniFormat
    )
    if _SHARED_PROFILE is None:
        parent = QCoreApplication.instance()
        if parent is None:
            raise RuntimeError("QApplication doit être créée avant le profil web.")
        root = browser_data_root()
        storage_path = root / "web-profile"
        cache_path = root / "web-cache"
        storage_path.mkdir(parents=True, exist_ok=True)
        cache_path.mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile("PublicRealTimeChecker", parent)
        profile.setPersistentStoragePath(str(storage_path))
        profile.setCachePath(str(cache_path))
        _SHARED_PROFILE = profile

    keep_sessions = settings.value("browser/keep_sessions", True, type=bool)
    policy = (
        QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        if keep_sessions
        else QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
    )
    _SHARED_PROFILE.setPersistentCookiesPolicy(policy)
    return _SHARED_PROFILE


def clear_browser_data(profile: QWebEngineProfile | None = None) -> None:
    active_profile = profile or _SHARED_PROFILE
    if active_profile is None:
        active_profile = configure_web_profile()
    active_profile.cookieStore().deleteAllCookies()
    active_profile.clearHttpCache()
    clear_permissions = getattr(active_profile, "clearAllVisitedLinks", None)
    if callable(clear_permissions):
        clear_permissions()
