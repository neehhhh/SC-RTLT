from __future__ import annotations

import sys

from PySide6.QtCore import QByteArray, QEvent, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QCursor, QEnterEvent, QRegion, QShowEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from .companion_widget import CompanionWidgetPage


_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WM_MOUSEACTIVATE = 0x0021
_MA_NOACTIVATE = 3


def _apply_windows_no_activate(hwnd: int) -> bool:
    """Add WS_EX_NOACTIVATE without changing any other native window style."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            get_style = user32.GetWindowLongPtrW
            set_style = user32.SetWindowLongPtrW
            style_type = ctypes.c_ssize_t
        else:
            get_style = user32.GetWindowLongW
            set_style = user32.SetWindowLongW
            style_type = ctypes.c_long
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = style_type
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, style_type]
        set_style.restype = style_type

        current = int(get_style(hwnd, _GWL_EXSTYLE))
        desired = current | _WS_EX_NOACTIVATE
        if desired != current:
            ctypes.set_last_error(0)
            result = int(set_style(hwnd, _GWL_EXSTYLE, desired))
            if result == 0 and ctypes.get_last_error() != 0:
                return False
        return bool(int(get_style(hwnd, _GWL_EXSTYLE)) & _WS_EX_NOACTIVATE)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


class WidgetWindow(QWidget):
    restore_requested = Signal()
    close_app_requested = Signal()
    settings_requested = Signal()

    # Main HUD kept at 548 × 78 px. A transparent centre gap separates
    # the left location/clock cluster from the right-aligned radio cluster.
    EXPANDED_SIZE = QSize(548, 78)
    COMPACT_SIZE = QSize(460, 72)
    # Compatibility names kept for existing integrations and diagnostics.
    EXPANDED_MINIMUM = EXPANDED_SIZE
    MINIMAL_HEIGHT = COMPACT_SIZE.height()
    DEFAULT_MINIMAL_DELAY_MS = 180_000
    HOVER_LOCK_MS = 5_000

    def __init__(self, settings: QSettings) -> None:
        super().__init__(None)
        self.settings = settings
        self._minimal_armed = False
        self._minimal_mode = False
        self._pending_leave = False
        self._game_ui_suppressed = False
        self._suppressed_was_visible = False
        self._suppressed_was_minimal = False
        self._inventory_compact_active = False
        self._inventory_was_visible = False
        self._inventory_was_minimal = False
        self.setWindowTitle("Public Real Time Checker - Widget")
        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.setFixedSize(self.EXPANDED_SIZE)

        self.page = CompanionWidgetPage(settings, self)
        self.page.mode_requested.connect(self._mode_requested)
        self.page.close_requested.connect(self.close_app_requested)
        self.page.settings_requested.connect(self.settings_requested)
        self.page.hud_region_changed.connect(self._update_hud_mask)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.page)

        self.minimal_timer = QTimer(self)
        self.minimal_timer.setSingleShot(True)
        self.minimal_timer.timeout.connect(self._arm_and_collapse)
        self.hover_lock_timer = QTimer(self)
        self.hover_lock_timer.setSingleShot(True)
        self.hover_lock_timer.setInterval(self.HOVER_LOCK_MS)
        self.hover_lock_timer.timeout.connect(self._hover_lock_expired)
        self.apply_settings()


    @property
    def game_ui_suppressed(self) -> bool:
        return self._game_ui_suppressed

    def set_game_ui_suppressed(self, suppressed: bool, *, restore: bool = True) -> None:
        """Temporarily hide without changing the user's selected widget mode."""
        suppressed = bool(suppressed)
        if suppressed == self._game_ui_suppressed:
            return
        if suppressed:
            self._game_ui_suppressed = True
            self._suppressed_was_visible = self.isVisible()
            self._suppressed_was_minimal = self._minimal_mode
            self.minimal_timer.stop()
            self.hover_lock_timer.stop()
            self._pending_leave = False
            self.hide()
            return

        was_visible = self._suppressed_was_visible and restore
        was_minimal = self._suppressed_was_minimal
        self._game_ui_suppressed = False
        self._suppressed_was_visible = False
        self._suppressed_was_minimal = False
        if not was_visible:
            return
        self.show_widget()
        if was_minimal and not self.is_lite:
            self.force_minimal()

    @property
    def inventory_compact_active(self) -> bool:
        return self._inventory_compact_active

    def set_inventory_compact(self, active: bool) -> None:
        """Compatibility hook. Inventory hiding is handled by full suppression."""
        self._inventory_compact_active = bool(active)
        self._inventory_was_visible = False
        self._inventory_was_minimal = False
        self.minimal_timer.stop()
        self.hover_lock_timer.stop()

    @property
    def minimal_mode(self) -> bool:
        return self._minimal_mode

    @property
    def widget_variant(self) -> str:
        return "widget"

    @property
    def is_lite(self) -> bool:
        return False

    def _mode_requested(self, widget_enabled: bool) -> None:
        if not widget_enabled:
            self.restore_requested.emit()

    def _configure_screen_surface(self) -> None:
        """Use the active screen as a transparent placement surface."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.setFixedSize(area.size())
        self.move(area.topLeft())
        self.page.set_hud_canvas_size(area.width(), area.height())
        self._update_hud_mask(self.page.hud_mask_rects())

    def _update_hud_mask(self, rects: object) -> None:
        region = QRegion()
        if isinstance(rects, (list, tuple)):
            for rect in rects:
                try:
                    region = region.united(QRegion(rect))
                except (TypeError, ValueError):
                    continue
        if region.isEmpty():
            self.clearMask()
        else:
            self.setMask(region)

    def _position_fixed_hud(self) -> None:
        # Compatibility name: the HUD now spans the active screen, while its
        # mask contains only the visible blocks.
        self._configure_screen_surface()

    def refresh_theme(self) -> None:
        self.page.refresh_theme()
        self.update()

    def apply_settings(self) -> None:
        self.page.apply_external_settings()
        self.minimal_timer.stop()
        self.hover_lock_timer.stop()
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            self.settings.value("widget/always_on_top", True, type=bool),
        )
        self.setWindowOpacity(1.0)
        if self.isVisible():
            self._apply_selected_variant()
            self._position_fixed_hud()
            self.show()

    def _apply_selected_variant(self) -> None:
        self.minimal_timer.stop()
        self.hover_lock_timer.stop()
        self._pending_leave = False
        self.page.set_lite_mode(False)
        self.page.set_minimal_mode(False)
        self._minimal_mode = False
        self._minimal_armed = False
        self._configure_screen_surface()

    def show_widget(self, geometry: QByteArray | None = None) -> None:
        del geometry  # Block positions are persisted by the HUD editor.
        self.setWindowOpacity(1.0)
        self.page.set_mode_switch(True)
        self._apply_selected_variant()
        self._position_fixed_hud()
        self.show()
        self.raise_()
        self._apply_no_activate_behavior()

    def show_minimal_widget(self, geometry: QByteArray | None = None) -> None:
        self.show_widget(geometry)

    def reveal_expanded(self) -> None:
        self._apply_selected_variant()
        self.show()
        self.raise_()
        self._apply_no_activate_behavior()

    def force_minimal(self) -> None:
        # Compatibility for the former Fn+F8 command: Mini no longer exists.
        self.reveal_expanded()

    def hide_widget(self) -> QByteArray:
        self.minimal_timer.stop()
        self.hover_lock_timer.stop()
        self._pending_leave = False
        geometry = self.saveGeometry()
        self.hide()
        return geometry

    def reset_geometry(self) -> None:
        self._minimal_armed = False
        self._pending_leave = False
        self.hover_lock_timer.stop()
        self._apply_selected_variant()
        self._position_fixed_hud()

    def _arm_and_collapse(self) -> None:
        self._minimal_armed = False

    def _pointer_over_window(self) -> bool:
        try:
            return self.underMouse() or self.frameGeometry().contains(QCursor.pos())
        except Exception:
            return self.underMouse()

    def _hover_lock_expired(self) -> None:
        self._pending_leave = False

    def _schedule_minimal_after_leave(self) -> None:
        self._minimal_armed = False
        self._pending_leave = False
        self.minimal_timer.stop()

    def _collapse_if_pointer_left(self) -> None:
        self._minimal_armed = False

    def collapse_to_minimal(self) -> None:
        self._apply_selected_variant()

    def expand_from_minimal(self, force: bool = False) -> None:
        del force
        self._apply_selected_variant()

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self.minimal_timer.stop()
        self.hover_lock_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self.minimal_timer.stop()
        self.hover_lock_timer.stop()
        super().leaveEvent(event)


    def _apply_no_activate_behavior(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if sys.platform == "win32":
            _apply_windows_no_activate(int(self.winId()))

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_no_activate_behavior()
        # Some flag changes recreate the HWND. Reapply after Qt finishes showing it.
        QTimer.singleShot(0, self._apply_no_activate_behavior)
        QTimer.singleShot(0, self._position_fixed_hud)

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                native_message = wintypes.MSG.from_address(int(message))
                if native_message.message == _WM_MOUSEACTIVATE:
                    return True, _MA_NOACTIVATE
            except (TypeError, ValueError, OSError, OverflowError):
                pass
        return super().nativeEvent(event_type, message)

    def shutdown(self) -> None:
        self.minimal_timer.stop()
        self.hover_lock_timer.stop()
        self.page.shutdown()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.close_app_requested.emit()
        event.ignore()
