from __future__ import annotations

import ctypes
import os
import sys
from importlib.resources import files

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-features=CalculateNativeWinOcclusion",
)

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .main_window import MainWindow
from .typography import apply_application_typography


def _set_windows_app_identity() -> None:
    """Give Windows a stable identity so the packaged icon is used on taskbar/windows."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("nehhh.PublicRealTimeChecker")
    except (AttributeError, OSError):
        pass


def main() -> int:
    _set_windows_app_identity()
    app = QApplication(sys.argv)
    app.setApplicationName("Public Real Time Checker")
    app.setOrganizationName("nehhh")
    app.setApplicationDisplayName("Public Real Time Checker")
    apply_application_typography(app)

    package_root = files("sc_web_companion")
    icon_names = ("assets/app_icon.ico", "assets/app_icon.png", "assets/app_icon.svg") if os.name == "nt" else ("assets/app_icon.png", "assets/app_icon.svg", "assets/app_icon.ico")
    for icon_name in icon_names:
        icon = package_root.joinpath(icon_name)
        if icon.is_file():
            app.setWindowIcon(QIcon(str(icon)))
            break

    try:
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Public Real Time Checker - erreur",
            f"L'application n'a pas pu démarrer.\n\n{type(exc).__name__}: {exc}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
