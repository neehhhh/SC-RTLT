from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget


class AppleSwitch(QAbstractButton):
    """Small iPhone-like on/off switch with an optional location accent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = QColor("#34c759")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self.setAccessibleName("Basculer entre l'application et le widget")

    def set_accent_color(self, color: str | QColor) -> None:
        candidate = QColor(color)
        if candidate.isValid():
            self._accent = candidate
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent if self.isChecked() else QColor(255, 255, 255, 58))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        diameter = self.height() - 6
        x = self.width() - diameter - 3 if self.isChecked() else 3
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, 3, diameter, diameter))


class DragLabel(QLabel):
    """Label that can drag the frameless widget window."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._drag_offset: QPoint | None = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)
