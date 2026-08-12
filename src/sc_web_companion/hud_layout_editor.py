from __future__ import annotations

from collections.abc import Callable, Mapping
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .hud_layout import (
    HUD_ELEMENT_SPECS,
    HUD_MAX_SCALE_PERCENT,
    HUD_MIN_SCALE_PERCENT,
    HUD_SPEC_BY_ID,
    HUD_TEXT_ELEMENT_IDS,
    crops_from_visible_widths,
    default_hud_crops,
    default_hud_scales,
    default_hud_text_alignments,
    default_hud_screen_layout,
    hud_visible_widths_from_crops,
    load_hud_crops,
    load_hud_groups,
    load_hud_scales,
    load_hud_screen_layout,
    load_hud_text_alignments,
    make_hud_screen_preview,
    normalize_hud_crops,
    normalize_hud_groups,
    normalize_hud_scales,
    normalize_hud_screen_layout,
    normalize_hud_text_alignments,
    save_hud_crops,
    save_hud_groups,
    save_hud_scales,
    save_hud_screen_layout,
    save_hud_text_alignments,
    scaled_hud_dimensions,
)
from .language import current_language, tr


class HudGraphicsItem(QGraphicsObject):
    _EDGE_MARGIN = 7.0
    _SCALE_HANDLE = 11.0

    def __init__(
        self,
        element_id: str,
        label: str,
        canvas: "HudEditorCanvas",
    ) -> None:
        super().__init__()
        self.element_id = element_id
        self.label = label
        self.canvas = canvas
        self._width = float(HUD_SPEC_BY_ID[element_id].width)
        self._height = float(HUD_SPEC_BY_ID[element_id].height)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(1)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0.0, 0.0, self._width, self._height)

    def set_visible_size(self, width: int, height: int) -> None:
        width = max(1, int(width))
        height = max(1, int(height))
        if width == int(self._width) and height == int(self._height):
            return
        self.prepareGeometryChange()
        self._width = float(width)
        self._height = float(height)
        self.update()

    def _mode_at(self, x: float, y: float) -> str:
        if (
            x >= max(0.0, self._width - self._SCALE_HANDLE)
            and y >= max(0.0, self._height - self._SCALE_HANDLE)
        ):
            return "scale"
        if x <= self._EDGE_MARGIN:
            return "left"
        if x >= max(0.0, self._width - self._EDGE_MARGIN):
            return "right"
        return "move"

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ANN001
        del option, widget
        selected = self.element_id in self.canvas.selected_ids
        grouped = self.canvas.group_for_element(self.element_id) is not None
        rect = self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_guide = self.element_id in {"guide_left", "guide_right"}
        painter.setBrush(QColor(38, 94, 126, 220) if selected else QColor(20, 31, 43, 215))
        border = QColor(104, 217, 255, 245) if selected else QColor(125, 140, 155, 210)
        painter.setPen(QPen(border, 1.0))
        painter.drawRoundedRect(rect, 3.0, 3.0)
        if is_guide:
            line = QLinearGradient(rect.left(), 0, rect.right(), 0)
            if self.element_id == "guide_left":
                line.setColorAt(0.0, QColor(82, 205, 255, 35))
                line.setColorAt(1.0, QColor(104, 217, 255, 245))
            else:
                line.setColorAt(0.0, QColor(104, 217, 255, 245))
                line.setColorAt(1.0, QColor(82, 205, 255, 35))
            painter.setPen(QPen(QColor(104, 217, 255, 220), 1.0))
            painter.setBrush(QBrush(line))
            painter.drawRoundedRect(rect.adjusted(4, 5, -4, -5), 2.0, 2.0)
        if grouped:
            painter.setPen(QPen(QColor(104, 217, 255, 150), 1.0, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 2.0, 2.0)
        painter.setPen(QColor(255, 255, 255, 235))
        font = painter.font()
        font.setPointSizeF(8.0)
        painter.setFont(font)
        text_alignment = Qt.AlignmentFlag.AlignCenter
        if self.element_id in HUD_TEXT_ELEMENT_IDS:
            text_alignment = (
                Qt.AlignmentFlag.AlignRight
                if self.canvas.current_alignments[self.element_id] == "right"
                else Qt.AlignmentFlag.AlignLeft
            ) | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(
            rect.adjusted(7, 1, -7, -1),
            text_alignment | Qt.TextFlag.TextWordWrap,
            self.label,
        )
        if selected:
            painter.setPen(QPen(QColor(104, 217, 255, 230), 1.0))
            for x in (3.0, 6.0, self._width - 4.0, self._width - 7.0):
                painter.drawLine(QPointF(x, 4.0), QPointF(x, max(4.0, self._height - 4.0)))
            handle = QRectF(
                max(1.0, self._width - self._SCALE_HANDLE),
                max(1.0, self._height - self._SCALE_HANDLE),
                self._SCALE_HANDLE - 2.0,
                self._SCALE_HANDLE - 2.0,
            )
            painter.setBrush(QColor(104, 217, 255, 220))
            painter.setPen(QPen(QColor(235, 252, 255, 245), 1.0))
            painter.drawRect(handle)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        mode = self._mode_at(event.pos().x(), event.pos().y())
        cursor = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "scale": Qt.CursorShape.SizeFDiagCursor,
        }.get(mode, Qt.CursorShape.SizeAllCursor)
        self.setCursor(cursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        mode = self._mode_at(event.pos().x(), event.pos().y())
        self.canvas.begin_interaction(
            self.element_id,
            mode,
            event.scenePos(),
            event.modifiers(),
        )
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        self.canvas.update_interaction(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        self.canvas.end_interaction()
        event.accept()


class HudEditorCanvas(QGraphicsView):
    layout_changed = Signal(object)
    selection_changed = Signal(str)

    def __init__(
        self,
        language: str,
        screen_width: int,
        screen_height: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.language = language
        self.screen_width = max(1, int(screen_width))
        self.screen_height = max(1, int(screen_height))
        self.setObjectName("hudEditorCanvas")
        self.setStyleSheet(
            "QGraphicsView#hudEditorCanvas { background: #07111d; border: 1px solid #4d6070; }"
        )
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMinimumSize(520, 300)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, self.screen_width, self.screen_height)
        self.setScene(self._scene)
        self._snap_enabled = True
        self._grid_size = 1
        self._auto_fit = True
        self._zoom_percent = 100
        self._primary_id = HUD_ELEMENT_SPECS[0].element_id
        self._selected_ids: set[str] = {self._primary_id}
        self._crops = default_hud_crops()
        self._scales = default_hud_scales()
        self._alignments = default_hud_text_alignments()
        self._layout = default_hud_screen_layout(self.screen_width, self.screen_height)
        self._groups: dict[str, list[str]] = {}
        self._items: dict[str, HudGraphicsItem] = {}
        self._interaction_mode = ""
        self._interaction_element = ""
        self._interaction_start = QPointF()
        self._interaction_layout: dict[str, tuple[int, int]] = {}
        self._interaction_crops: dict[str, dict[str, int]] = {}
        self._interaction_scales: dict[str, int] = {}
        sample_text = {
            "controls": "×   ◉   ON",
            "location": "SERAPHIM",
            "pc_clock": "11:42",
            "verse_clock": "18:06",
            "radio_info": "PEOPLE'S RADIO   35%",
            "media": "◀◀  ▶  ▶▶",
            "track": "ARTISTE — TITRE",
            "guide_left": "BARRE G",
            "guide_right": "BARRE D",
        }
        for spec in HUD_ELEMENT_SPECS:
            item = HudGraphicsItem(
                spec.element_id,
                sample_text.get(
                    spec.element_id,
                    spec.label_en if language == "en" else spec.label_fr,
                ),
                self,
            )
            self._scene.addItem(item)
            self._items[spec.element_id] = item
        self.set_screen_layout(
            self._layout,
            self._crops,
            self._groups,
            self._scales,
            self._alignments,
            emit=False,
        )
        self._refresh_selection()

    @property
    def current_layout(self) -> dict[str, tuple[int, int]]:
        return dict(self._layout)

    @property
    def current_crops(self) -> dict[str, dict[str, int]]:
        return {key: dict(value) for key, value in self._crops.items()}

    @property
    def current_widths(self) -> dict[str, int]:
        return hud_visible_widths_from_crops(self._crops)

    @property
    def current_scales(self) -> dict[str, int]:
        return dict(self._scales)

    @property
    def current_alignments(self) -> dict[str, str]:
        return dict(self._alignments)

    @property
    def current_groups(self) -> dict[str, list[str]]:
        return {name: list(members) for name, members in self._groups.items()}

    @property
    def current_preview(self) -> dict[str, object]:
        return make_hud_screen_preview(
            self._layout,
            self._crops,
            self._groups,
            self.screen_width,
            self.screen_height,
            self._scales,
            self._alignments,
        )

    @property
    def selected_id(self) -> str:
        return self._primary_id

    @property
    def selected_ids(self) -> tuple[str, ...]:
        order = [spec.element_id for spec in HUD_ELEMENT_SPECS]
        return tuple(element_id for element_id in order if element_id in self._selected_ids)

    def set_snap(self, enabled: bool, grid_size: int) -> None:
        self._snap_enabled = bool(enabled)
        self._grid_size = max(1, int(grid_size))
        self.viewport().update()

    def set_zoom(self, percent: int) -> None:
        self._auto_fit = False
        self._zoom_percent = max(20, min(200, int(percent)))
        self.resetTransform()
        factor = self._zoom_percent / 100.0
        self.scale(factor, factor)

    def fit_screen(self) -> None:
        self._auto_fit = True
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_screen()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        painter.fillRect(rect, QColor(7, 17, 29))
        if self._snap_enabled and self._grid_size >= 4:
            step = self._grid_size
            painter.setPen(QPen(QColor(92, 123, 146, 55), 1))
            left = int(rect.left()) - (int(rect.left()) % step)
            top = int(rect.top()) - (int(rect.top()) % step)
            x = left
            while x <= int(rect.right()):
                painter.drawLine(x, rect.top(), x, rect.bottom())
                x += step
            y = top
            while y <= int(rect.bottom()):
                painter.drawLine(rect.left(), y, rect.right(), y)
                y += step
        painter.setPen(QPen(QColor(82, 205, 255, 90), 1, Qt.PenStyle.DashLine))
        painter.drawLine(self.screen_width / 2, 0, self.screen_width / 2, self.screen_height)
        painter.drawLine(0, self.screen_height / 2, self.screen_width, self.screen_height / 2)
        painter.setPen(QPen(QColor(125, 140, 155, 180), 2))
        painter.drawRect(QRectF(0, 0, self.screen_width, self.screen_height))

    def set_screen_layout(
        self,
        layout: Mapping[str, object],
        crops: Mapping[str, object] | None = None,
        groups: object = None,
        scales: Mapping[str, object] | None = None,
        text_alignments: Mapping[str, object] | None = None,
        *,
        emit: bool = True,
    ) -> None:
        self._crops = normalize_hud_crops(crops)
        self._scales = normalize_hud_scales(scales)
        self._alignments = normalize_hud_text_alignments(text_alignments)
        self._layout = normalize_hud_screen_layout(
            layout,
            self._crops,
            self.screen_width,
            self.screen_height,
            self._scales,
        )
        self._groups = normalize_hud_groups(groups)
        widths = self.current_widths
        for element_id, (x, y) in self._layout.items():
            spec = HUD_SPEC_BY_ID[element_id]
            item = self._items[element_id]
            scaled_width, scaled_height = scaled_hud_dimensions(
                spec, widths[element_id], self._scales[element_id]
            )
            item.set_visible_size(scaled_width, scaled_height)
            item.setPos(x, y)
        self._selected_ids &= set(self._items)
        if not self._selected_ids:
            self._selected_ids = {self._primary_id}
        self._refresh_selection()
        if emit:
            self._emit_changed()

    # Compatibility with the v1 editor API.
    def set_layout(
        self,
        layout: Mapping[str, object],
        widths: Mapping[str, object] | None = None,
        *,
        emit: bool = True,
    ) -> None:
        self.set_screen_layout(
            layout,
            crops_from_visible_widths(widths),
            self._groups,
            self._scales,
            self._alignments,
            emit=emit,
        )

    def _emit_changed(self) -> None:
        self.layout_changed.emit(self.current_preview)

    def group_for_element(self, element_id: str) -> str | None:
        for name, members in self._groups.items():
            if element_id in members:
                return name
        return None

    def _selection_for_click(self, element_id: str) -> set[str]:
        group_name = self.group_for_element(element_id)
        if group_name is not None:
            return set(self._groups[group_name])
        return {element_id}

    def select_element(
        self,
        element_id: str,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        if element_id not in self._items:
            return
        click_selection = self._selection_for_click(element_id)
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if element_id in self._selected_ids:
                self._selected_ids.discard(element_id)
            else:
                self._selected_ids.add(element_id)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            self._selected_ids.update(click_selection)
        else:
            self._selected_ids = click_selection
        if not self._selected_ids:
            self._selected_ids = {element_id}
        self._primary_id = element_id
        self._refresh_selection()
        self.selection_changed.emit(element_id)

    def select_group(self, group_name: str) -> None:
        members = self._groups.get(group_name, [])
        if not members:
            return
        self._selected_ids = set(members)
        self._primary_id = members[0]
        self._refresh_selection()
        self.selection_changed.emit(self._primary_id)

    def _refresh_selection(self) -> None:
        for element_id, item in self._items.items():
            item.setZValue(10 if element_id in self._selected_ids else 1)
            item.update()

    def begin_interaction(
        self,
        element_id: str,
        mode: str,
        scene_pos: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        if mode == "move":
            if element_id not in self._selected_ids or modifiers:
                self.select_element(element_id, modifiers)
        else:
            # Cropping and proportional scaling are deliberately per block,
            # even when its group is selected.
            self._primary_id = element_id
            self._selected_ids = {element_id}
            self.selection_changed.emit(element_id)
            self._refresh_selection()
        self._interaction_mode = mode
        self._interaction_element = element_id
        self._interaction_start = QPointF(scene_pos)
        self._interaction_layout = dict(self._layout)
        self._interaction_crops = self.current_crops
        self._interaction_scales = self.current_scales

    def update_interaction(self, scene_pos: QPointF) -> None:
        if not self._interaction_mode:
            return
        delta_x = int(round(scene_pos.x() - self._interaction_start.x()))
        delta_y = int(round(scene_pos.y() - self._interaction_start.y()))
        if self._interaction_mode == "move":
            self._drag_selected(delta_x, delta_y)
        elif self._interaction_mode == "scale":
            self._scale_element(
                self._interaction_element, delta_x, delta_y
            )
        else:
            self._resize_edge(
                self._interaction_element,
                self._interaction_mode,
                delta_x,
            )

    def end_interaction(self) -> None:
        self._interaction_mode = ""
        self._interaction_element = ""
        self._interaction_layout = {}
        self._interaction_crops = {}
        self._interaction_scales = {}

    def _snap_value(self, value: int) -> int:
        if not self._snap_enabled:
            return int(value)
        grid = self._grid_size
        return round(int(value) / grid) * grid

    def _drag_selected(self, dx: int, dy: int) -> None:
        selected = self.selected_ids
        if not selected:
            return
        primary_x, primary_y = self._interaction_layout[self._primary_id]
        snapped_x = self._snap_value(primary_x + dx)
        snapped_y = self._snap_value(primary_y + dy)
        dx = snapped_x - primary_x
        dy = snapped_y - primary_y
        widths = self.current_widths
        dimensions = {
            element_id: scaled_hud_dimensions(
                HUD_SPEC_BY_ID[element_id],
                widths[element_id],
                self._scales[element_id],
            )
            for element_id in selected
        }
        min_dx = max(-self._interaction_layout[element_id][0] for element_id in selected)
        max_dx = min(
            self.screen_width
            - dimensions[element_id][0]
            - self._interaction_layout[element_id][0]
            for element_id in selected
        )
        min_dy = max(-self._interaction_layout[element_id][1] for element_id in selected)
        max_dy = min(
            self.screen_height
            - dimensions[element_id][1]
            - self._interaction_layout[element_id][1]
            for element_id in selected
        )
        dx = max(min_dx, min(max_dx, dx))
        dy = max(min_dy, min(max_dy, dy))
        for element_id in selected:
            x, y = self._interaction_layout[element_id]
            self._layout[element_id] = (x + dx, y + dy)
            self._items[element_id].setPos(x + dx, y + dy)
        self._emit_changed()

    def _resize_edge(self, element_id: str, edge: str, delta: int) -> None:
        spec = HUD_SPEC_BY_ID[element_id]
        original_crop = self._interaction_crops[element_id]
        scale_percent = self._interaction_scales[element_id]
        scale = scale_percent / 100.0
        left = original_crop["left"]
        right = original_crop["right"]
        x, y = self._interaction_layout[element_id]
        visible = spec.width - left - right
        scaled_visible, scaled_height = scaled_hud_dimensions(
            spec, visible, scale_percent
        )
        if edge == "left":
            target_edge = self._snap_value(x + delta)
            screen_delta = target_edge - x
            native_delta = int(round(screen_delta / max(0.01, scale)))
            minimum_native = max(-left, int(math.ceil(-x / max(0.01, scale))))
            maximum_native = visible - spec.minimum_width
            native_delta = max(minimum_native, min(maximum_native, native_delta))
            actual_delta = int(round(native_delta * scale))
            new_left = left + native_delta
            new_right = right
            new_x = x + actual_delta
        else:
            target_edge = self._snap_value(x + scaled_visible + delta)
            screen_delta = target_edge - (x + scaled_visible)
            native_delta = int(round(screen_delta / max(0.01, scale)))
            minimum_native = -(visible - spec.minimum_width)
            maximum_native = right
            native_delta = max(minimum_native, min(maximum_native, native_delta))
            actual_new_width = int(round((visible + native_delta) * scale))
            if x + actual_new_width > self.screen_width:
                maximum_screen = max(1, self.screen_width - x)
                maximum_visible = int(maximum_screen / max(0.01, scale))
                native_delta = min(native_delta, maximum_visible - visible)
            new_left = left
            new_right = right - native_delta
            new_x = x
        self._crops[element_id] = {"left": int(new_left), "right": int(new_right)}
        new_native_width = spec.width - int(new_left) - int(new_right)
        new_width, new_height = scaled_hud_dimensions(
            spec, new_native_width, scale_percent
        )
        self._layout[element_id] = (int(new_x), y)
        item = self._items[element_id]
        item.set_visible_size(new_width, new_height)
        item.setPos(int(new_x), y)
        self._emit_changed()

    def _scale_element(self, element_id: str, dx: int, dy: int) -> None:
        spec = HUD_SPEC_BY_ID[element_id]
        crop = self._interaction_crops[element_id]
        visible = spec.width - crop["left"] - crop["right"]
        original_scale = self._interaction_scales[element_id]
        original_width, original_height = scaled_hud_dimensions(
            spec, visible, original_scale
        )
        width_ratio = abs(dx) / max(1, original_width)
        height_ratio = abs(dy) / max(1, original_height)
        if width_ratio >= height_ratio:
            target = int(round((original_width + dx) * 100 / max(1, visible)))
        else:
            target = int(round((original_height + dy) * 100 / max(1, spec.height)))
        x, y = self._interaction_layout[element_id]
        maximum_width_scale = int((max(1, self.screen_width - x) * 100) / max(1, visible))
        maximum_height_scale = int((max(1, self.screen_height - y) * 100) / max(1, spec.height))
        maximum = min(HUD_MAX_SCALE_PERCENT, maximum_width_scale, maximum_height_scale)
        target = max(HUD_MIN_SCALE_PERCENT, min(maximum, target))
        self._set_element_scale(element_id, target, emit=True)

    def _set_element_scale(
        self, element_id: str, percent: int, *, emit: bool = True
    ) -> None:
        spec = HUD_SPEC_BY_ID[element_id]
        crop = self._crops[element_id]
        visible = spec.width - crop["left"] - crop["right"]
        x, y = self._layout[element_id]
        maximum_width_scale = int((max(1, self.screen_width - x) * 100) / max(1, visible))
        maximum_height_scale = int((max(1, self.screen_height - y) * 100) / max(1, spec.height))
        maximum = min(HUD_MAX_SCALE_PERCENT, maximum_width_scale, maximum_height_scale)
        percent = max(HUD_MIN_SCALE_PERCENT, min(maximum, int(percent)))
        self._scales[element_id] = percent
        width, height = scaled_hud_dimensions(spec, visible, percent)
        item = self._items[element_id]
        item.set_visible_size(width, height)
        item.setPos(x, y)
        if emit:
            self._emit_changed()

    def set_scale_percent(self, element_id: str, percent: int) -> None:
        if element_id not in self._items:
            return
        self._primary_id = element_id
        self._set_element_scale(element_id, percent, emit=True)

    def set_text_alignment(self, element_id: str, alignment: str) -> None:
        if element_id not in HUD_TEXT_ELEMENT_IDS:
            return
        normalized = normalize_hud_text_alignments(
            {**self._alignments, element_id: alignment}
        )
        if normalized[element_id] == self._alignments[element_id]:
            return
        self._alignments = normalized
        self._items[element_id].update()
        self._emit_changed()

    def move_element(self, element_id: str, x: int, y: int) -> None:
        if element_id not in self._items:
            return
        self._selected_ids = {element_id}
        self._primary_id = element_id
        current_x, current_y = self._layout[element_id]
        self._interaction_layout = dict(self._layout)
        self._drag_selected(int(x) - current_x, int(y) - current_y)
        self._interaction_layout = {}
        self._refresh_selection()
        self.selection_changed.emit(element_id)

    def move_selection_to_primary(self, x: int, y: int) -> None:
        current_x, current_y = self._layout[self._primary_id]
        base = dict(self._layout)
        self._interaction_layout = base
        self._drag_selected(int(x) - current_x, int(y) - current_y)
        self._interaction_layout = {}

    def set_crop_values(self, element_id: str, left: int, right: int) -> None:
        spec = HUD_SPEC_BY_ID[element_id]
        old = self._crops[element_id]
        scale_percent = self._scales[element_id]
        scale = scale_percent / 100.0
        left = max(0, int(left))
        right = max(0, int(right))
        maximum_total = spec.width - spec.minimum_width
        left = min(left, maximum_total)
        right = min(right, maximum_total - left)
        x, y = self._layout[element_id]
        delta_left_native = left - old["left"]
        delta_left_screen = int(round(delta_left_native * scale))
        if x + delta_left_screen < 0:
            maximum_native = int(math.floor(x / max(0.01, scale)))
            delta_left_native = -maximum_native
            left = old["left"] + delta_left_native
            delta_left_screen = int(round(delta_left_native * scale))
        new_native_width = spec.width - left - right
        new_width, new_height = scaled_hud_dimensions(
            spec, new_native_width, scale_percent
        )
        new_x = x + delta_left_screen
        if new_x + new_width > self.screen_width:
            overflow = new_x + new_width - self.screen_width
            extra_native_crop = int(math.ceil(overflow / max(0.01, scale)))
            right = min(maximum_total - left, right + extra_native_crop)
            new_native_width = spec.width - left - right
            new_width, new_height = scaled_hud_dimensions(
                spec, new_native_width, scale_percent
            )
        self._crops[element_id] = {"left": left, "right": right}
        self._layout[element_id] = (new_x, y)
        item = self._items[element_id]
        item.set_visible_size(new_width, new_height)
        item.setPos(new_x, y)
        self._primary_id = element_id
        self._emit_changed()

    def resize_element(self, element_id: str, width: int) -> None:
        spec = HUD_SPEC_BY_ID[element_id]
        left = self._crops[element_id]["left"]
        maximum = spec.width - left
        width = max(spec.minimum_width, min(maximum, int(width)))
        self.set_crop_values(element_id, left, spec.width - left - width)

    def nudge_selected(self, dx: int, dy: int) -> None:
        base = dict(self._layout)
        self._interaction_layout = base
        self._drag_selected(int(dx), int(dy))
        self._interaction_layout = {}

    def _selection_bounds(self) -> tuple[int, int, int, int]:
        widths = self.current_widths
        selected = self.selected_ids
        dimensions = {
            element_id: scaled_hud_dimensions(
                HUD_SPEC_BY_ID[element_id],
                widths[element_id],
                self._scales[element_id],
            )
            for element_id in selected
        }
        left = min(self._layout[element_id][0] for element_id in selected)
        top = min(self._layout[element_id][1] for element_id in selected)
        right = max(
            self._layout[element_id][0] + dimensions[element_id][0]
            for element_id in selected
        )
        bottom = max(
            self._layout[element_id][1] + dimensions[element_id][1]
            for element_id in selected
        )
        return left, top, right, bottom

    def align_selected(
        self, horizontal: str | None = None, vertical: str | None = None
    ) -> None:
        left, top, right, bottom = self._selection_bounds()
        dx = 0
        dy = 0
        if horizontal == "left":
            dx = -left
        elif horizontal == "center":
            dx = (self.screen_width - (right - left)) // 2 - left
        elif horizontal == "right":
            dx = self.screen_width - right
        if vertical == "top":
            dy = -top
        elif vertical == "middle":
            dy = (self.screen_height - (bottom - top)) // 2 - top
        elif vertical == "bottom":
            dy = self.screen_height - bottom
        self.nudge_selected(dx, dy)

    def group_selected(self) -> str | None:
        members = list(self.selected_ids)
        if len(members) < 2:
            return None
        self.ungroup_selected(emit=False)
        index = 1
        while f"Groupe {index}" in self._groups:
            index += 1
        name = f"Groupe {index}"
        self._groups[name] = members
        self._refresh_selection()
        self._emit_changed()
        return name

    def ungroup_selected(self, *, emit: bool = True) -> None:
        selected = set(self._selected_ids)
        changed = False
        for name in list(self._groups):
            members = [member for member in self._groups[name] if member not in selected]
            if len(members) < 2:
                if len(members) != len(self._groups[name]):
                    changed = True
                del self._groups[name]
            elif members != self._groups[name]:
                self._groups[name] = members
                changed = True
        if changed:
            self._refresh_selection()
            if emit:
                self._emit_changed()

    def reset_selected(self) -> None:
        defaults = default_hud_screen_layout(self.screen_width, self.screen_height)
        default_crops = default_hud_crops()
        default_scales = default_hud_scales()
        default_alignments = default_hud_text_alignments()
        default_widths = hud_visible_widths_from_crops(default_crops)
        for element_id in self.selected_ids:
            self._crops[element_id] = dict(default_crops[element_id])
            self._scales[element_id] = default_scales[element_id]
            if element_id in HUD_TEXT_ELEMENT_IDS:
                self._alignments[element_id] = default_alignments[element_id]
            self._layout[element_id] = defaults[element_id]
            spec = HUD_SPEC_BY_ID[element_id]
            displayed_width, displayed_height = scaled_hud_dimensions(
                spec, default_widths[element_id], default_scales[element_id]
            )
            item = self._items[element_id]
            item.set_visible_size(displayed_width, displayed_height)
            item.setPos(*defaults[element_id])
        self._emit_changed()

    def reset_all(self) -> None:
        self._selected_ids = {HUD_ELEMENT_SPECS[0].element_id}
        self._primary_id = HUD_ELEMENT_SPECS[0].element_id
        self.set_screen_layout(
            default_hud_screen_layout(self.screen_width, self.screen_height),
            default_hud_crops(),
            {},
            default_hud_scales(),
            default_hud_text_alignments(),
        )
        self.selection_changed.emit(self._primary_id)


class HudLayoutEditor(QDialog):
    def __init__(
        self,
        settings,
        preview_callback: Callable[[Mapping[str, object] | None], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.language = current_language(settings)
        self.preview_callback = preview_callback
        screen = parent.screen() if parent is not None else None
        screen = screen or QApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else None
        self.screen_width = geometry.width() if geometry is not None else 1920
        self.screen_height = geometry.height() if geometry is not None else 1080
        self._original_crops = load_hud_crops(settings)
        self._original_groups = load_hud_groups(settings)
        self._original_scales = load_hud_scales(settings)
        self._original_alignments = load_hud_text_alignments(settings)
        self._original_layout = load_hud_screen_layout(
            settings,
            self.screen_width,
            self.screen_height,
            self._original_crops,
            self._original_scales,
        )
        self._accepted = False
        self.setWindowTitle(tr(settings, "Éditeur du HUD", "HUD editor"))
        self.setModal(False)

        intro = QLabel(
            tr(
                settings,
                "Tirez le bord gauche ou droit pour recadrer sans changer l’échelle. Tirez le carré inférieur droit pour agrandir ou réduire le bloc en conservant son rapport hauteur/largeur. Ctrl/Shift sélectionnent plusieurs blocs ; groupez-les pour conserver leur déplacement commun sur tout l’écran.",
                "Drag either edge to crop without changing scale. Drag the lower-right square to enlarge or reduce the block while preserving its height/width ratio. Ctrl/Shift select several blocks; group them to keep moving together across the whole screen.",
            )
        )
        intro.setWordWrap(True)

        self.canvas = HudEditorCanvas(
            self.language, self.screen_width, self.screen_height
        )
        self.canvas.set_screen_layout(
            self._original_layout,
            self._original_crops,
            self._original_groups,
            self._original_scales,
            self._original_alignments,
            emit=False,
        )
        self.canvas.layout_changed.connect(self._on_layout_changed)
        self.canvas.selection_changed.connect(self._on_selection_changed)

        self.element_combo = QComboBox()
        for spec in HUD_ELEMENT_SPECS:
            self.element_combo.addItem(
                spec.label_en if self.language == "en" else spec.label_fr,
                spec.element_id,
            )
        self.element_combo.currentIndexChanged.connect(self._combo_selection_changed)

        self.selection_label = QLabel()
        self.text_alignment_combo = QComboBox()
        self.text_alignment_combo.addItem(tr(settings, "Gauche", "Left"), "left")
        self.text_alignment_combo.addItem(tr(settings, "Droite", "Right"), "right")
        self.text_alignment_combo.currentIndexChanged.connect(
            self._text_alignment_changed
        )
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self._group_combo_changed)
        group_button = QPushButton(tr(settings, "Grouper la sélection", "Group selection"))
        group_button.clicked.connect(self._group_selection)
        ungroup_button = QPushButton(tr(settings, "Dégrouper", "Ungroup"))
        ungroup_button.clicked.connect(self._ungroup_selection)

        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, self.screen_width)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, self.screen_height)
        self.x_spin.valueChanged.connect(self._spin_position_changed)
        self.y_spin.valueChanged.connect(self._spin_position_changed)

        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(HUD_MIN_SCALE_PERCENT, HUD_MAX_SCALE_PERCENT)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(HUD_MIN_SCALE_PERCENT, HUD_MAX_SCALE_PERCENT)
        self.scale_spin.setSuffix(" %")
        self.scale_slider.valueChanged.connect(self._scale_slider_changed)
        self.scale_spin.valueChanged.connect(self._scale_spin_changed)
        self.scaled_size_label = QLabel()

        self.left_crop_slider = QSlider(Qt.Orientation.Horizontal)
        self.left_crop_spin = QSpinBox()
        self.left_crop_spin.setSuffix(" px")
        self.right_crop_slider = QSlider(Qt.Orientation.Horizontal)
        self.right_crop_spin = QSpinBox()
        self.right_crop_spin.setSuffix(" px")
        self.left_crop_slider.valueChanged.connect(self._left_slider_changed)
        self.left_crop_spin.valueChanged.connect(self._left_spin_changed)
        self.right_crop_slider.valueChanged.connect(self._right_slider_changed)
        self.right_crop_spin.valueChanged.connect(self._right_spin_changed)
        self.visible_width_label = QLabel()

        self.snap_check = QCheckBox(tr(settings, "Aimantation", "Snap to grid"))
        self.snap_check.setChecked(True)
        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(1, 64)
        self.grid_spin.setSuffix(" px")
        self.grid_spin.setValue(1)
        self.snap_check.toggled.connect(self._snap_changed)
        self.grid_spin.valueChanged.connect(self._snap_changed)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(20, 200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self.canvas.set_zoom)
        fit_button = QPushButton(tr(settings, "Adapter l’écran", "Fit screen"))
        fit_button.clicked.connect(self.canvas.fit_screen)

        arrows = QGridLayout()
        up = QPushButton("↑")
        left = QPushButton("←")
        right = QPushButton("→")
        down = QPushButton("↓")
        up.clicked.connect(lambda: self.canvas.nudge_selected(0, -1))
        left.clicked.connect(lambda: self.canvas.nudge_selected(-1, 0))
        right.clicked.connect(lambda: self.canvas.nudge_selected(1, 0))
        down.clicked.connect(lambda: self.canvas.nudge_selected(0, 1))
        arrows.addWidget(up, 0, 1)
        arrows.addWidget(left, 1, 0)
        arrows.addWidget(right, 1, 2)
        arrows.addWidget(down, 2, 1)

        align = QGridLayout()
        align_actions = (
            (tr(settings, "Gauche écran", "Screen left"), "left", None, 0, 0),
            (tr(settings, "Centre", "Center"), "center", None, 0, 1),
            (tr(settings, "Droite écran", "Screen right"), "right", None, 0, 2),
            (tr(settings, "Haut écran", "Screen top"), None, "top", 1, 0),
            (tr(settings, "Milieu", "Middle"), None, "middle", 1, 1),
            (tr(settings, "Bas écran", "Screen bottom"), None, "bottom", 1, 2),
        )
        for text, horizontal, vertical, row, column in align_actions:
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, h=horizontal, v=vertical: self.canvas.align_selected(h, v)
            )
            align.addWidget(button, row, column)

        reset_selected = QPushButton(
            tr(settings, "Réinitialiser la sélection", "Reset selection")
        )
        reset_selected.clicked.connect(self.canvas.reset_selected)
        reset_all = QPushButton(tr(settings, "Disposition d’origine", "Default layout"))
        reset_all.clicked.connect(self.canvas.reset_all)

        controls = QFrame()
        controls.setFrameShape(QFrame.Shape.StyledPanel)
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(QLabel(tr(settings, "Bloc principal", "Primary block")))
        controls_layout.addWidget(self.element_combo)
        controls_layout.addWidget(self.selection_label)
        controls_layout.addWidget(
            QLabel(tr(settings, "Alignement du texte", "Text alignment"))
        )
        controls_layout.addWidget(self.text_alignment_combo)
        controls_layout.addWidget(QLabel(tr(settings, "Groupes enregistrés", "Saved groups")))
        controls_layout.addWidget(self.group_combo)
        group_row = QHBoxLayout()
        group_row.addWidget(group_button)
        group_row.addWidget(ungroup_button)
        controls_layout.addLayout(group_row)
        xy_row = QHBoxLayout()
        xy_row.addWidget(QLabel("X"))
        xy_row.addWidget(self.x_spin)
        xy_row.addWidget(QLabel("Y"))
        xy_row.addWidget(self.y_spin)
        controls_layout.addLayout(xy_row)
        controls_layout.addWidget(
            QLabel(tr(settings, "Échelle liée H × L", "Linked H × W scale"))
        )
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_spin)
        controls_layout.addLayout(scale_row)
        controls_layout.addWidget(self.scaled_size_label)
        controls_layout.addWidget(QLabel(tr(settings, "Recadrage gauche", "Left crop")))
        left_row = QHBoxLayout()
        left_row.addWidget(self.left_crop_slider, 1)
        left_row.addWidget(self.left_crop_spin)
        controls_layout.addLayout(left_row)
        controls_layout.addWidget(QLabel(tr(settings, "Recadrage droit", "Right crop")))
        right_row = QHBoxLayout()
        right_row.addWidget(self.right_crop_slider, 1)
        right_row.addWidget(self.right_crop_spin)
        controls_layout.addLayout(right_row)
        controls_layout.addWidget(self.visible_width_label)
        snap_row = QHBoxLayout()
        snap_row.addWidget(self.snap_check)
        snap_row.addWidget(self.grid_spin)
        controls_layout.addLayout(snap_row)
        controls_layout.addLayout(arrows)
        controls_layout.addLayout(align)
        controls_layout.addWidget(QLabel(tr(settings, "Zoom de l’éditeur", "Editor zoom")))
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(self.zoom_slider, 1)
        zoom_row.addWidget(fit_button)
        controls_layout.addLayout(zoom_row)
        controls_layout.addWidget(reset_selected)
        controls_layout.addWidget(reset_all)
        controls_layout.addStretch(1)

        content = QHBoxLayout()
        canvas_column = QVBoxLayout()
        canvas_column.addWidget(self.canvas, 1)
        note = QLabel(
            tr(
                settings,
                "La bordure extérieure représente l’écran actif. Les blocs peuvent être séparés, rapprochés ou regroupés. Le fond transparent entre eux ne bloque pas les clics dans le jeu.",
                "The outer border represents the active screen. Blocks can be separated, brought together or grouped. Transparent space between them does not block clicks in the game.",
            )
        )
        note.setWordWrap(True)
        canvas_column.addWidget(note)
        content.addLayout(canvas_column, 1)
        controls_scroll = QScrollArea()
        controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        controls_scroll.setMinimumWidth(280)
        controls_scroll.setWidget(controls)
        content.addWidget(controls_scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            tr(settings, "Enregistrer", "Save")
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr(settings, "Annuler", "Cancel")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(content, 1)
        layout.addWidget(buttons)
        self._on_selection_changed(self.canvas.selected_id)
        self._refresh_group_combo()
        default_width = min(960, max(760, self.screen_width - 80))
        default_height = min(620, max(520, self.screen_height - 80))
        self.resize(default_width, default_height)
        self.canvas.fit_screen()

    def _refresh_group_combo(self) -> None:
        current = self.group_combo.currentData()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem(tr(self.settings, "Aucun groupe", "No group"), "")
        for name, members in self.canvas.current_groups.items():
            self.group_combo.addItem(f"{name} ({len(members)})", name)
        index = self.group_combo.findData(current)
        self.group_combo.setCurrentIndex(max(0, index))
        self.group_combo.blockSignals(False)

    def _on_layout_changed(self, preview: Mapping[str, object]) -> None:
        self._sync_controls(self.canvas.selected_id)
        self._refresh_group_combo()
        self.preview_callback(preview)

    def _sync_controls(self, element_id: str) -> None:
        x, y = self.canvas.current_layout[element_id]
        crop = self.canvas.current_crops[element_id]
        spec = HUD_SPEC_BY_ID[element_id]
        visible = spec.width - crop["left"] - crop["right"]
        scale_percent = self.canvas.current_scales[element_id]
        scaled_width, scaled_height = scaled_hud_dimensions(
            spec, visible, scale_percent
        )
        widgets = (
            self.x_spin,
            self.y_spin,
            self.scale_slider,
            self.scale_spin,
            self.left_crop_slider,
            self.left_crop_spin,
            self.right_crop_slider,
            self.right_crop_spin,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.x_spin.setMaximum(max(0, self.screen_width - scaled_width))
        self.y_spin.setMaximum(max(0, self.screen_height - scaled_height))
        self.x_spin.setValue(x)
        self.y_spin.setValue(y)
        maximum_scale = min(
            HUD_MAX_SCALE_PERCENT,
            int((max(1, self.screen_width - x) * 100) / max(1, visible)),
            int((max(1, self.screen_height - y) * 100) / max(1, spec.height)),
        )
        maximum_scale = max(HUD_MIN_SCALE_PERCENT, maximum_scale)
        self.scale_slider.setRange(HUD_MIN_SCALE_PERCENT, maximum_scale)
        self.scale_spin.setRange(HUD_MIN_SCALE_PERCENT, maximum_scale)
        self.scale_slider.setValue(scale_percent)
        self.scale_spin.setValue(scale_percent)
        max_crop = spec.width - spec.minimum_width
        self.left_crop_slider.setRange(0, max_crop - crop["right"])
        self.left_crop_spin.setRange(0, max_crop - crop["right"])
        self.right_crop_slider.setRange(0, max_crop - crop["left"])
        self.right_crop_spin.setRange(0, max_crop - crop["left"])
        self.left_crop_slider.setValue(crop["left"])
        self.left_crop_spin.setValue(crop["left"])
        self.right_crop_slider.setValue(crop["right"])
        self.right_crop_spin.setValue(crop["right"])
        for widget in widgets:
            widget.blockSignals(False)
        supports_alignment = element_id in HUD_TEXT_ELEMENT_IDS
        self.text_alignment_combo.blockSignals(True)
        self.text_alignment_combo.setEnabled(supports_alignment)
        if supports_alignment:
            alignment_index = self.text_alignment_combo.findData(
                self.canvas.current_alignments[element_id]
            )
            self.text_alignment_combo.setCurrentIndex(max(0, alignment_index))
            self.text_alignment_combo.setToolTip("")
        else:
            self.text_alignment_combo.setCurrentIndex(0)
            self.text_alignment_combo.setToolTip(
                tr(
                    self.settings,
                    "Ce bloc ne contient pas de texte alignable.",
                    "This block has no alignable text.",
                )
            )
        self.text_alignment_combo.blockSignals(False)
        self.scaled_size_label.setText(
            tr(
                self.settings,
                f"Taille affichée : {scaled_width} × {scaled_height} px",
                f"Displayed size: {scaled_width} × {scaled_height} px",
            )
        )
        self.visible_width_label.setText(
            tr(
                self.settings,
                f"Zone visible : {visible} px sur {spec.width} px",
                f"Visible area: {visible} px of {spec.width} px",
            )
        )
        self.selection_label.setText(
            tr(
                self.settings,
                f"Sélection : {len(self.canvas.selected_ids)} bloc(s)",
                f"Selection: {len(self.canvas.selected_ids)} block(s)",
            )
        )

    def _on_selection_changed(self, element_id: str) -> None:
        index = self.element_combo.findData(element_id)
        self.element_combo.blockSignals(True)
        self.element_combo.setCurrentIndex(max(0, index))
        self.element_combo.blockSignals(False)
        self._sync_controls(element_id)

    def _combo_selection_changed(self, _index: int = -1) -> None:
        element_id = str(self.element_combo.currentData() or "")
        self.canvas.select_element(element_id)

    def _text_alignment_changed(self, _index: int = -1) -> None:
        element_id = self.canvas.selected_id
        alignment = str(self.text_alignment_combo.currentData() or "left")
        self.canvas.set_text_alignment(element_id, alignment)

    def _group_combo_changed(self, _index: int = -1) -> None:
        name = str(self.group_combo.currentData() or "")
        if name:
            self.canvas.select_group(name)

    def _group_selection(self) -> None:
        name = self.canvas.group_selected()
        self._refresh_group_combo()
        if name:
            index = self.group_combo.findData(name)
            self.group_combo.setCurrentIndex(max(0, index))

    def _ungroup_selection(self) -> None:
        self.canvas.ungroup_selected()
        self._refresh_group_combo()

    def _spin_position_changed(self, _value: int = 0) -> None:
        self.canvas.move_selection_to_primary(self.x_spin.value(), self.y_spin.value())

    def _set_left_crop(self, value: int) -> None:
        element_id = self.canvas.selected_id
        right = self.canvas.current_crops[element_id]["right"]
        self.canvas.set_crop_values(element_id, value, right)

    def _set_right_crop(self, value: int) -> None:
        element_id = self.canvas.selected_id
        left = self.canvas.current_crops[element_id]["left"]
        self.canvas.set_crop_values(element_id, left, value)

    def _left_slider_changed(self, value: int) -> None:
        self._set_left_crop(value)

    def _left_spin_changed(self, value: int) -> None:
        self._set_left_crop(value)

    def _right_slider_changed(self, value: int) -> None:
        self._set_right_crop(value)

    def _right_spin_changed(self, value: int) -> None:
        self._set_right_crop(value)

    def _set_scale_percent(self, value: int) -> None:
        self.canvas.set_scale_percent(self.canvas.selected_id, value)

    def _scale_slider_changed(self, value: int) -> None:
        self._set_scale_percent(value)

    def _scale_spin_changed(self, value: int) -> None:
        self._set_scale_percent(value)

    def _snap_changed(self, _value: object = None) -> None:
        self.canvas.set_snap(self.snap_check.isChecked(), self.grid_spin.value())

    def accept(self) -> None:
        crops = save_hud_crops(self.settings, self.canvas.current_crops)
        scales = save_hud_scales(self.settings, self.canvas.current_scales)
        save_hud_text_alignments(self.settings, self.canvas.current_alignments)
        save_hud_screen_layout(
            self.settings,
            self.canvas.current_layout,
            crops,
            self.screen_width,
            self.screen_height,
            scales,
        )
        save_hud_groups(self.settings, self.canvas.current_groups)
        self.preview_callback(None)
        self._accepted = True
        super().accept()

    def reject(self) -> None:
        if not self._accepted:
            self.preview_callback(
                make_hud_screen_preview(
                    self._original_layout,
                    self._original_crops,
                    self._original_groups,
                    self.screen_width,
                    self.screen_height,
                    self._original_scales,
                    self._original_alignments,
                )
            )
            self.preview_callback(None)
        super().reject()
