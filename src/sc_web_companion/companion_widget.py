from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSettings, QSignalBlocker, QTime, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QBrush,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .controls import AppleSwitch
from .hud_color import (
    DEFAULT_HUD_COLOR,
    DEFAULT_HUD_SECONDARY_COLOR,
    HUD_COLOR_SETTINGS_KEY,
    HUD_SECONDARY_COLOR_SETTINGS_KEY,
    hud_theme_colors,
    normalize_hud_color,
    normalize_hud_secondary_color,
)
from .language import current_language, tr, translate_location_name, translate_weather
from .hud_layout import (
    HUD_CANVAS_HEIGHT,
    HUD_CANVAS_WIDTH,
    HUD_ELEMENT_SPECS,
    HUD_PREVIEW_CROPS_KEY,
    HUD_PREVIEW_SCALES_KEY,
    HUD_PREVIEW_SCREEN_SIZE_KEY,
    HUD_PREVIEW_TEXT_ALIGNMENTS_KEY,
    HUD_PREVIEW_WIDTHS_KEY,
    crops_from_visible_widths,
    hud_visible_widths_from_crops,
    load_hud_crops,
    load_hud_scales,
    load_hud_screen_layout,
    load_hud_text_alignments,
    normalize_hud_crops,
    normalize_hud_scales,
    normalize_hud_screen_layout,
    normalize_hud_text_alignments,
)
from .radio_engine import RadioEngine
from .radio_page import (
    DEFAULT_STATION_ID,
    RadioStation,
    STATION_BY_ID,
    playable_stations,
    station_streams,
)
from .display_policy import secondary_display
from .verse_time import (
    LOCATION_BY_ID,
    VERSE_LOCATIONS,
    body_is_moon,
    location_uses_utc_clock,
    normalize_location_id,
    resolve_verse_location,
    visual_location_id_for_body,
)
from .weather_simulation import simulate_weather, simulate_weather_for_location
from .typography import apply_technical_font
from .theme_loader import DEFAULT_WIDGET_VISUAL, WidgetVisualTheme


@dataclass(frozen=True, slots=True)
class SpaceTheme:
    accent: str
    highlight: str
    deep: str
    effect: str
    planet_x: float = 0.82
    planet_y: float = 1.03
    planet_radius: float = 0.64


# The widget does not use background pictures. Locations select scene effects
# and vector geometry; the visible HUD colour is chosen manually in Settings.
SPACE_THEMES: dict[str, SpaceTheme] = {
    "new-babbage": SpaceTheme("#7fd9ee", "#e5fbff", "#102c42", "ice", 0.84, 1.04, 0.66),
    "lorville": SpaceTheme("#cf744f", "#ffd5ae", "#3b211c", "industrial", 0.83, 1.05, 0.68),
    "area18": SpaceTheme("#d66ea8", "#91dcff", "#25172f", "city", 0.85, 1.05, 0.65),
    "orison": SpaceTheme("#e6a8c8", "#d9ecff", "#34223f", "gas", 0.86, 1.06, 0.70),
    "daymar": SpaceTheme("#cba06b", "#f3dfbd", "#382b1d", "desert", 0.84, 1.04, 0.68),
    "yela": SpaceTheme("#a9c8df", "#f0f8ff", "#1c2c3b", "ice", 0.83, 1.03, 0.67),
    "aberdeen": SpaceTheme("#dd6d3f", "#ffd09b", "#422017", "heat", 0.84, 1.05, 0.69),
    "arial": SpaceTheme("#d49a55", "#ffe1ad", "#3d2a18", "desert", 0.84, 1.04, 0.67),
    "calliope": SpaceTheme("#8cc8e6", "#effcff", "#132b3d", "ice", 0.85, 1.06, 0.69),
    "clio": SpaceTheme("#b0cbe1", "#f5fbff", "#1c2d3c", "ice", 0.84, 1.05, 0.66),
    "euterpe": SpaceTheme("#8fb4cd", "#eef8ff", "#192c3b", "mist", 0.85, 1.07, 0.68),
}
DEFAULT_THEME = SPACE_THEMES["new-babbage"]
_CUSTOM_SPACE_THEMES: dict[str, SpaceTheme] = {}
_CUSTOM_DEFAULT_THEME: SpaceTheme | None = None
_CUSTOM_WIDGET_VISUAL: WidgetVisualTheme = DEFAULT_WIDGET_VISUAL
DECOR_OPACITY = 88


def set_custom_space_themes(
    default_theme: SpaceTheme | None = None,
    location_themes: dict[str, SpaceTheme] | None = None,
) -> None:
    """Load optional scene/effect overrides without replacing the manual HUD colour."""
    global _CUSTOM_DEFAULT_THEME
    _CUSTOM_DEFAULT_THEME = default_theme
    _CUSTOM_SPACE_THEMES.clear()
    for key, theme in (location_themes or {}).items():
        normalized = str(key or "").strip().casefold().replace("_", "-")
        if normalized:
            _CUSTOM_SPACE_THEMES[normalized] = theme


def active_space_theme(location_id: str) -> SpaceTheme:
    normalized = normalize_location_id(location_id)
    return (
        _CUSTOM_SPACE_THEMES.get(normalized)
        or _CUSTOM_DEFAULT_THEME
        or SPACE_THEMES.get(normalized)
        or DEFAULT_THEME
    )


def manual_hud_space_theme(
    hud_color: object,
    location_id: str = "new-babbage",
    secondary_color: object | None = None,
) -> SpaceTheme:
    """Keep both HUD colours manual while preserving scene geometry."""
    accent, highlight, deep = hud_theme_colors(hud_color, secondary_color)
    scene_theme = active_space_theme(location_id)
    return SpaceTheme(
        accent,
        highlight,
        deep,
        scene_theme.effect,
        scene_theme.planet_x,
        scene_theme.planet_y,
        scene_theme.planet_radius,
    )


def active_vehicle_space_theme(
    manufacturer_id: str | None, vehicle_code: str | None = None
) -> SpaceTheme:
    """Compatibility helper: vehicle identity no longer changes HUD colours."""
    del manufacturer_id, vehicle_code
    return manual_hud_space_theme(DEFAULT_HUD_COLOR)


def set_custom_widget_visual_style(style: WidgetVisualTheme | None = None) -> None:
    """Replace the safe visual treatment without replacing the manual HUD colour."""
    global _CUSTOM_WIDGET_VISUAL
    _CUSTOM_WIDGET_VISUAL = style or DEFAULT_WIDGET_VISUAL


def active_widget_visual_style() -> WidgetVisualTheme:
    return _CUSTOM_WIDGET_VISUAL


def _rgba(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, alpha)))
    return result


class SpaceCard(QFrame):
    """Transparent vector backdrop drawn dynamically for the selected location."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("companionCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.location_id = "new-babbage"
        self.location_kind = "surface"
        self.scene_kind = "surface"
        self.vehicle_manufacturer = ""
        self.vehicle_code = ""
        self.hud_color = DEFAULT_HUD_COLOR
        self.hud_secondary_color = DEFAULT_HUD_SECONDARY_COLOR
        self.theme = manual_hud_space_theme(
            self.hud_color, self.location_id, self.hud_secondary_color
        )
        self.visual_style = active_widget_visual_style()
        self.background_opacity = 88
        self.minimal_mode = False
        self.phase_label = "Nuit"
        self.is_daylight = False
        self.is_full_daylight = False
        self.weather_key = "sunny"
        self.weather_label = "Soleil"
        self._drag_offset: QPoint | None = None
        self._animation_tick = 0
        self._weather_seed = 0
        self.hud_strip_mode = False
        self.hud_bars_visible = True
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(150)
        self.animation_timer.timeout.connect(self._advance_animation)
        self.animation_timer.start()

    def _advance_animation(self) -> None:
        self._animation_tick = (self._animation_tick + 1) % 240
        if self.isVisible():
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self.hud_strip_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            not self.hud_strip_mode
            and self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def refresh_theme(self) -> None:
        self.theme = manual_hud_space_theme(
            self.hud_color, self.location_id, self.hud_secondary_color
        )
        self.visual_style = active_widget_visual_style()
        self.update()

    def set_hud_color(self, color: object) -> None:
        normalized = normalize_hud_color(color)
        if normalized == self.hud_color:
            return
        self.hud_color = normalized
        self.refresh_theme()

    def set_hud_secondary_color(self, color: object) -> None:
        normalized = normalize_hud_secondary_color(color)
        if normalized == self.hud_secondary_color:
            return
        self.hud_secondary_color = normalized
        self.refresh_theme()

    def set_hud_colors(self, primary: object, secondary: object) -> None:
        normalized_primary = normalize_hud_color(primary)
        normalized_secondary = normalize_hud_secondary_color(secondary)
        if (
            normalized_primary == self.hud_color
            and normalized_secondary == self.hud_secondary_color
        ):
            return
        self.hud_color = normalized_primary
        self.hud_secondary_color = normalized_secondary
        self.refresh_theme()

    def set_vehicle_context(
        self, manufacturer_id: str | None, vehicle_code: str | None = None
    ) -> None:
        # Retained for Game.log compatibility only. Vehicle changes must never
        # alter the manually selected HUD colour.
        self.vehicle_manufacturer = str(manufacturer_id or "").strip().casefold()
        self.vehicle_code = str(vehicle_code or "").strip()

    def set_location(self, location_id: str) -> None:
        self.location_id = normalize_location_id(location_id)
        self.location_kind = LOCATION_BY_ID[self.location_id].kind
        self.refresh_theme()

    def set_scene(
        self,
        location_id: str,
        phase: str,
        weather_key: str,
        weather_label: str,
        is_daylight: bool,
        is_full_daylight: bool,
        scene_kind: str = "surface",
    ) -> None:
        self.location_id = normalize_location_id(location_id)
        self.location_kind = LOCATION_BY_ID[self.location_id].kind
        self.theme = manual_hud_space_theme(
            self.hud_color, self.location_id, self.hud_secondary_color
        )
        self.visual_style = active_widget_visual_style()
        self.phase_label = str(phase or "")
        self.weather_key = str(weather_key or "sunny")
        self.weather_label = str(weather_label or "")
        self.is_daylight = bool(is_daylight)
        self.is_full_daylight = bool(is_full_daylight)
        self.scene_kind = str(scene_kind or "surface").strip().casefold()
        if self.scene_kind not in {"surface", "moon", "station", "space"}:
            self.scene_kind = "surface"
        self._weather_seed = sum(f"{self.location_id}:{weather_key}:{phase}".encode("utf-8"))
        self.update()

    def set_hud_strip_mode(self, enabled: bool) -> None:
        """Use the fixed transparent 1920×1080 HUD treatment."""
        self.hud_strip_mode = bool(enabled)
        self._drag_offset = None
        self.setCursor(
            Qt.CursorShape.ArrowCursor if self.hud_strip_mode else Qt.CursorShape.SizeAllCursor
        )
        if self.hud_strip_mode:
            self.animation_timer.stop()
        elif not self.animation_timer.isActive():
            self.animation_timer.start()
        self.update()

    def set_hud_bars_visible(self, visible: bool) -> None:
        self.hud_bars_visible = bool(visible)
        self.update()

    def _paint_hud_bars(self, painter: QPainter, rect) -> None:
        """Draw two thin cyan guides with a soft 85% horizontal fade."""
        y = float(rect.bottom()) - 10.0
        center = float(rect.center().x())
        gap = max(74.0, min(112.0, rect.width() * 0.13))
        shoulder = max(42.0, min(78.0, rect.width() * 0.085))

        left = QPainterPath()
        left.moveTo(float(rect.left()) + 2.0, y - 8.0)
        left.lineTo(float(rect.left()) + shoulder, y - 7.0)
        left.lineTo(float(rect.left()) + shoulder + 24.0, y)
        left.lineTo(center - gap, y)

        right = QPainterPath()
        right.moveTo(center + gap, y)
        right.lineTo(float(rect.right()) - shoulder - 24.0, y)
        right.lineTo(float(rect.right()) - shoulder, y - 7.0)
        right.lineTo(float(rect.right()) - 2.0, y - 8.0)

        def gradient(start_x: float, end_x: float, reverse: bool = False) -> QLinearGradient:
            result = QLinearGradient(start_x, y, end_x, y)
            peak = int(255 * 0.85)
            colors = [
                QColor(47, 159, 208, int(peak * 0.16)),
                QColor(70, 201, 242, int(peak * 0.62)),
                QColor(99, 227, 255, peak),
                QColor(70, 201, 242, int(peak * 0.62)),
                QColor(47, 159, 208, int(peak * 0.16)),
            ]
            stops = (0.0, 0.18, 0.52, 0.82, 1.0)
            if reverse:
                colors.reverse()
            for stop, color in zip(stops, colors):
                result.setColorAt(stop, color)
            return result

        def draw(path: QPainterPath, brush: QBrush) -> None:
            # One very light glow plus the sharp 0.70 px guide.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(brush, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setOpacity(0.18)
            painter.drawPath(path)
            painter.setPen(QPen(brush, 0.70, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setOpacity(1.0)
            painter.drawPath(path)
            painter.setOpacity(1.0)

        draw(left, QBrush(gradient(float(rect.left()) + 2.0, center - gap)))
        draw(right, QBrush(gradient(center + gap, float(rect.right()) - 2.0, reverse=True)))

    def set_background_opacity(self, value: int) -> None:
        """Change only the painted backdrop; child controls remain fully opaque."""
        self.background_opacity = max(5, min(100, int(value)))
        self.update()

    def set_minimal_mode(self, enabled: bool) -> None:
        self.minimal_mode = bool(enabled)
        self.update()

    def _planet_geometry(self, rect, *, minimal: bool = False) -> tuple[float, float, float]:
        """Return the scene-specific planet centre and radius."""
        if minimal:
            if self.scene_kind == "moon":
                return (
                    rect.left() + rect.height() * 0.58,
                    rect.bottom() + rect.height() * 0.02,
                    rect.height() * 0.56,
                )
            return (
                rect.left() + rect.height() * 0.72,
                rect.bottom() + rect.height() * 0.18,
                rect.height() * 0.94,
            )

        width = float(rect.width())
        height = float(rect.height())
        radius = height * self.theme.planet_radius
        x = rect.left() + width * self.theme.planet_x
        y = rect.top() + height * self.theme.planet_y
        if self.scene_kind == "moon":
            radius *= 0.55
            y -= height * 0.18
        elif self.scene_kind == "station":
            radius *= 0.82
        return x, y, radius

    def _frame_radius(self, rect) -> float:
        style = self.visual_style.frame_style
        radius = min(float(self.visual_style.corner_radius), rect.height() * 0.24)
        if style == "industrial":
            return min(radius, 9.0)
        if style == "hud":
            return min(radius, 3.0)
        if style == "minimal":
            return min(radius, 5.0)
        return radius

    def _frame_path(self, rect, radius: float) -> QPainterPath:
        path = QPainterPath()
        if self.visual_style.frame_style == "industrial":
            cut = min(max(5.0, radius), rect.height() * 0.18, rect.width() * 0.08)
            path.moveTo(rect.left() + cut, rect.top())
            path.lineTo(rect.right() - cut, rect.top())
            path.lineTo(rect.right(), rect.top() + cut)
            path.lineTo(rect.right(), rect.bottom() - cut)
            path.lineTo(rect.right() - cut, rect.bottom())
            path.lineTo(rect.left() + cut, rect.bottom())
            path.lineTo(rect.left(), rect.bottom() - cut)
            path.lineTo(rect.left(), rect.top() + cut)
            path.closeSubpath()
        else:
            path.addRoundedRect(rect, radius, radius)
        return path

    def _paint_visual_background(
        self,
        painter: QPainter,
        rect,
        accent: QColor,
        highlight: QColor,
    ) -> None:
        visual = self.visual_style
        width = float(rect.width())
        height = float(rect.height())
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if visual.grid_opacity > 0.001:
            alpha = int(255 * visual.grid_opacity)
            painter.setPen(QPen(_rgba(accent, alpha), 0.65))
            spacing_x = max(16, int(width / 12))
            spacing_y = max(13, int(height / 9))
            x = int(rect.left()) + spacing_x
            while x < rect.right():
                painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
                x += spacing_x
            y = int(rect.top()) + spacing_y
            while y < rect.bottom():
                painter.drawLine(int(rect.left()), y, int(rect.right()), y)
                y += spacing_y

        if visual.scanline_opacity > 0.001:
            alpha = int(255 * visual.scanline_opacity)
            painter.setPen(QPen(_rgba(highlight, alpha), 0.55))
            for y in range(int(rect.top()) + 3, int(rect.bottom()), 5):
                painter.drawLine(int(rect.left()), y, int(rect.right()), y)

        if visual.glass_highlight > 0.001:
            sheen = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
            peak = int(255 * visual.glass_highlight)
            sheen.setColorAt(0.0, _rgba(highlight, peak))
            sheen.setColorAt(0.23, _rgba(highlight, max(0, peak // 3)))
            sheen.setColorAt(0.48, QColor(255, 255, 255, 0))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(sheen)
            painter.drawRect(rect)
        painter.restore()

    def _paint_frame(
        self,
        painter: QPainter,
        rect,
        radius: float,
        accent: QColor,
        highlight: QColor,
    ) -> None:
        visual = self.visual_style
        style = visual.frame_style
        path = self._frame_path(rect, radius)
        width = float(max(0.4, visual.border_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if style == "glass":
            painter.setPen(QPen(_rgba(highlight, 155), width))
            painter.drawPath(path)
            if visual.inner_border:
                inner = rect.adjusted(2, 2, -2, -2)
                painter.setPen(QPen(_rgba(accent, 70), max(0.5, width * 0.65)))
                painter.drawPath(self._frame_path(inner, max(0.0, radius - 2)))
        elif style == "industrial":
            painter.setPen(QPen(_rgba(accent, 205), width + 0.25))
            painter.drawPath(path)
            if visual.inner_border:
                inner = rect.adjusted(2, 2, -2, -2)
                painter.setPen(QPen(_rgba(highlight, 72), max(0.55, width * 0.65)))
                painter.drawPath(self._frame_path(inner, max(4.0, radius - 2)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_rgba(highlight, 145))
            for point in (
                QPointF(rect.left() + 8, rect.top() + 8),
                QPointF(rect.right() - 8, rect.top() + 8),
                QPointF(rect.left() + 8, rect.bottom() - 8),
                QPointF(rect.right() - 8, rect.bottom() - 8),
            ):
                painter.drawEllipse(point, 1.4, 1.4)
        elif style == "hud":
            painter.setPen(QPen(_rgba(accent, 98), max(0.5, width * 0.7)))
            painter.drawPath(path)
        elif style == "minimal":
            painter.setPen(QPen(_rgba(accent, 145), max(0.5, width * 0.72)))
            painter.drawPath(path)
        else:
            painter.setPen(QPen(_rgba(accent, 96), width))
            painter.drawPath(path)
            if visual.inner_border:
                painter.setPen(QPen(_rgba(highlight, 54), max(0.5, width * 0.7)))
                painter.drawPath(self._frame_path(rect.adjusted(1, 1, -1, -1), max(0.0, radius - 1)))

        if style == "hud" or visual.corner_marks:
            length = min(18.0, rect.height() * 0.18)
            inset = 4.0
            painter.setPen(QPen(_rgba(highlight, 205), max(0.8, width)))
            corners = (
                (rect.left() + inset, rect.top() + inset, 1, 1),
                (rect.right() - inset, rect.top() + inset, -1, 1),
                (rect.left() + inset, rect.bottom() - inset, 1, -1),
                (rect.right() - inset, rect.bottom() - inset, -1, -1),
            )
            for x, y, sx, sy in corners:
                painter.drawLine(int(x), int(y), int(x + sx * length), int(y))
                painter.drawLine(int(x), int(y), int(x), int(y + sy * length))

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        rect = self.rect().adjusted(1, 1, -1, -1)
        if self.hud_strip_mode:
            if self.hud_bars_visible:
                self._paint_hud_bars(painter, rect)
            painter.end()
            return
        radius = self._frame_radius(rect)
        clip = self._frame_path(rect, radius)
        painter.setClipPath(clip)

        accent = QColor(self.theme.accent)
        highlight = QColor(self.theme.highlight)
        deep = QColor(self.theme.deep)
        visual = self.visual_style
        strength = (self.background_opacity / 100.0) * visual.panel_opacity

        def alpha(base: int) -> int:
            return max(1, min(255, round(base * strength)))

        if self.minimal_mode:
            # Keep the requested depth order in the reduced and Lite variants too:
            # panel background, station, foreground planet, then the interface.
            self._paint_visual_background(painter, rect, accent, highlight)
            if self.scene_kind != "space":
                planet_x, planet_y, planet_radius = self._planet_geometry(rect, minimal=True)
                if self.scene_kind == "station":
                    # Same swap as the normal widget: small planet at upper centre,
                    # large station in the former planet position.
                    planet_x = rect.left() + rect.width() * 0.25
                    planet_y = rect.top() + rect.height() * 0.30
                    planet_radius = rect.height() * 0.18
                    self._paint_station_scene(
                        painter, rect,
                        rect.left() + rect.width() * 0.72,
                        rect.bottom() + rect.height() * 0.20,
                        rect.height() * 1.48,
                        accent, highlight, deep,
                    )
                painter.save()
                painter.setOpacity(visual.planet_intensity)
                planet = QRadialGradient(
                    planet_x - planet_radius * (0.46 if self.is_daylight else 0.14),
                    planet_y - planet_radius * 0.52,
                    planet_radius * 1.18,
                )
                if self.is_daylight:
                    planet.setColorAt(0.0, _rgba(highlight, 122))
                    planet.setColorAt(0.34, _rgba(accent, 96))
                    planet.setColorAt(0.78, _rgba(deep, 58))
                else:
                    planet.setColorAt(0.0, _rgba(highlight, 54))
                    planet.setColorAt(0.32, _rgba(accent, 66))
                    planet.setColorAt(0.76, _rgba(deep, 92))
                planet.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(planet)
                painter.drawEllipse(
                    int(planet_x - planet_radius),
                    int(planet_y - planet_radius),
                    int(planet_radius * 2),
                    int(planet_radius * 2),
                )
                painter.restore()
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                for index, (x, y) in enumerate(((0.18, 0.30), (0.39, 0.62), (0.61, 0.25), (0.82, 0.55))):
                    breath = (math.sin(self._animation_tick * 0.10 + index * 1.9) + 1.0) * 0.5
                    painter.setBrush(_rgba(highlight, 48 + int(58 * breath)))
                    size = 1 + int(breath * 1.2)
                    painter.drawEllipse(
                        int(rect.left() + rect.width() * x),
                        int(rect.top() + rect.height() * y),
                        size, size,
                    )
            painter.setClipping(False)
            self._paint_frame(painter, rect, radius, accent, highlight)
            return

        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if self.is_daylight:
            base.setColorAt(0.0, QColor(8, 14, 22, alpha(205)))
            base.setColorAt(0.46, _rgba(deep, alpha(182)))
            base.setColorAt(1.0, _rgba(accent, alpha(148)))
        else:
            base.setColorAt(0.0, QColor(3, 7, 13, alpha(236)))
            base.setColorAt(0.60, _rgba(deep, alpha(218)))
            base.setColorAt(1.0, _rgba(accent, alpha(138)))
        painter.fillPath(clip, base)

        veil = QLinearGradient(rect.left(), 0, rect.right(), 0)
        if self.is_daylight:
            veil.setColorAt(0.0, QColor(4, 8, 14, alpha(210)))
            veil.setColorAt(0.58, QColor(4, 8, 14, alpha(122)))
            veil.setColorAt(1.0, QColor(4, 8, 14, alpha(18)))
        else:
            veil.setColorAt(0.0, QColor(2, 5, 10, alpha(232)))
            veil.setColorAt(0.56, QColor(2, 5, 10, alpha(160)))
            veil.setColorAt(1.0, QColor(2, 5, 10, alpha(42)))
        painter.fillPath(clip, veil)
        self._paint_visual_background(painter, rect, accent, highlight)

        width = float(rect.width())
        height = float(rect.height())
        planet_x, planet_y, planet_radius = self._planet_geometry(rect)
        if self.scene_kind == "station":
            # Swap the former subjects: the parent planet becomes the small distant
            # object and the station takes the large lower-right focal position.
            planet_x = rect.left() + width * 0.80
            planet_y = rect.top() + height * 0.24
            planet_radius = height * 0.18

        if self.scene_kind == "surface" or self.scene_kind == "moon":
            painter.save()
            painter.setOpacity(visual.weather_intensity)
            self._paint_weather_background(
                painter, rect, planet_x, planet_y, planet_radius,
                accent, highlight, deep,
            )
            painter.restore()
        elif self.scene_kind == "station":
            painter.save()
            painter.setOpacity(max(0.35, visual.effect_intensity))
            self._paint_station_scene(
                painter, rect,
                rect.left() + width * self.theme.planet_x,
                rect.top() + height * self.theme.planet_y,
                height * 1.72,
                accent, highlight, deep,
            )
            painter.restore()

        if self.scene_kind != "space":
            painter.save()
            painter.setOpacity(visual.planet_intensity)
            planet = QRadialGradient(
                planet_x - planet_radius * (0.48 if self.is_daylight else 0.18),
                planet_y - planet_radius * 0.52,
                planet_radius * 1.24,
            )
            if self.is_daylight:
                planet.setColorAt(0.0, _rgba(highlight, 225))
                planet.setColorAt(0.30, _rgba(accent, 182))
                planet.setColorAt(0.72, _rgba(deep, 145))
            else:
                planet.setColorAt(0.0, _rgba(highlight, 78))
                planet.setColorAt(0.24, _rgba(accent, 74))
                planet.setColorAt(0.62, _rgba(deep, 148))
                planet.setColorAt(0.88, QColor(1, 3, 8, 214))
            planet.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(planet)
            painter.drawEllipse(
                int(planet_x - planet_radius),
                int(planet_y - planet_radius),
                int(planet_radius * 2),
                int(planet_radius * 2),
            )
            self._paint_day_night_variant(
                painter, rect, planet_x, planet_y, planet_radius,
                accent, highlight, deep,
            )
            painter.restore()

        painter.save()
        painter.setOpacity(visual.orbit_intensity)
        orbit = QPainterPath()
        if self.scene_kind not in {"station", "space"}:
            orbit.moveTo(rect.left() + width * 0.30, rect.top() + height * 0.50)
            orbit.cubicTo(
                rect.left() + width * 0.48,
                rect.top() + height * 0.29,
                rect.left() + width * 0.70,
                rect.top() + height * 0.18,
                rect.left() + width * 0.96,
                rect.top() + height * 0.28,
            )
            orbit_pen = QPen(_rgba(highlight, 46 if self.is_daylight else 58), 0.8)
            orbit_pen.setStyle(Qt.PenStyle.DashLine)
            orbit_pen.setDashOffset(self._animation_tick * 0.45)
            painter.setPen(orbit_pen)
            painter.drawPath(orbit)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_rgba(highlight, 150 if self.is_daylight else 185))
            moon_x = rect.left() + width * 0.55
            moon_y = rect.top() + height * 0.34
            moon_breath = (self._animation_tick % 18) / 18.0
            painter.drawEllipse(int(moon_x - 2), int(moon_y - 2), 4, 4)
            painter.setBrush(_rgba(accent, 52 + int(20 * moon_breath)))
            painter.drawEllipse(int(moon_x - 5), int(moon_y - 5), 10, 10)
        painter.restore()

        if self.scene_kind == "space":
            # Sparse, calm deep-space field: a few points breathe independently.
            deep_points = (
                (0.12, 0.22, 1.5), (0.27, 0.58, 1.0), (0.42, 0.31, 1.2),
                (0.58, 0.71, 1.0), (0.69, 0.19, 1.4), (0.83, 0.48, 1.1),
                (0.92, 0.27, 1.0), (0.76, 0.80, 1.3),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            for index, (x, y, size) in enumerate(deep_points):
                breath = (math.sin(self._animation_tick * 0.10 + index * 1.7) + 1.0) * 0.5
                painter.setBrush(_rgba(highlight, 55 + int(65 * breath)))
                diameter = max(1, int(size + breath * 1.4))
                painter.drawEllipse(
                    int(rect.left() + width * x), int(rect.top() + height * y),
                    diameter, diameter,
                )

        star_points = (
            (0.10, 0.18, 1.0), (0.24, 0.28, 0.7), (0.38, 0.17, 0.8),
            (0.49, 0.62, 0.6), (0.63, 0.13, 0.7), (0.73, 0.45, 0.6),
            (0.91, 0.14, 0.8), (0.82, 0.33, 0.7), (0.15, 0.44, 0.7),
        )
        offset = sum(self.location_id.encode("utf-8")) % len(star_points)
        base_star_total = 4 if self.is_daylight else 8
        star_total = min(len(star_points), round(base_star_total * visual.star_density))
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(star_total):
            x, y, size = star_points[(index + offset) % len(star_points)]
            twinkle = 72 + ((self._animation_tick + index * 17) % 55)
            painter.setBrush(_rgba(highlight, twinkle if not self.is_daylight else max(40, twinkle - 40)))
            painter.drawEllipse(
                int(rect.left() + width * x), int(rect.top() + height * y),
                max(1, int(size)), max(1, int(size)),
            )

        if self.scene_kind == "surface" or self.scene_kind == "moon":
            painter.save()
            painter.setOpacity(visual.effect_intensity)
            self._paint_effect(painter, rect, accent, highlight)
            painter.restore()
            painter.save()
            painter.setOpacity(visual.weather_intensity)
            self._paint_weather_foreground(painter, rect, accent, highlight, deep)
            painter.restore()

        painter.setClipping(False)
        self._paint_frame(painter, rect, radius, accent, highlight)

    def _paint_station_scene(
        self,
        painter: QPainter,
        rect,
        center_x: float,
        center_y: float,
        radius: float,
        accent: QColor,
        highlight: QColor,
        deep: QColor,
    ) -> None:
        """Draw a station layer behind the foreground planet."""
        width = float(rect.width())
        height = float(rect.height())
        station_x = center_x - radius * 0.10
        station_y = center_y - radius * 0.38
        ring = max(32.0, radius * 0.42)

        # The parent planet is painted later so the station sits between it and the panel.
        painter.save()
        painter.translate(station_x, station_y)
        painter.rotate((self._animation_tick * 1.1) % 360)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_rgba(highlight, 205 if self.is_daylight else 150), 1.35))
        painter.drawEllipse(int(-ring), int(-ring * 0.52), int(ring * 2), int(ring * 1.04))
        painter.setPen(QPen(_rgba(accent, 145 if self.is_daylight else 110), 0.9))
        painter.drawEllipse(int(-ring * 0.72), int(-ring * 0.36), int(ring * 1.44), int(ring * 0.72))
        for angle in (0, 60, 120):
            radians = math.radians(angle)
            painter.drawLine(
                int(-math.cos(radians) * ring), int(-math.sin(radians) * ring * 0.52),
                int(math.cos(radians) * ring), int(math.sin(radians) * ring * 0.52),
            )
        painter.restore()

        # Central body, mast and solar/radiator panels.
        panel_alpha = 178 if self.is_daylight else 86
        painter.setPen(QPen(_rgba(highlight, 170 if self.is_daylight else 120), 1.0))
        painter.setBrush(_rgba(deep, 210 if self.is_daylight else 235))
        core_w = max(18, int(radius * 0.10))
        core_h = max(28, int(radius * 0.16))
        painter.drawRoundedRect(
            int(station_x - core_w / 2), int(station_y - core_h / 2),
            core_w, core_h, 5, 5
        )
        painter.drawLine(
            int(station_x), int(station_y - core_h / 2),
            int(station_x), int(station_y - core_h * 1.25)
        )
        painter.drawLine(
            int(station_x), int(station_y + core_h / 2),
            int(station_x), int(station_y + core_h * 1.05)
        )
        painter.setBrush(_rgba(accent, panel_alpha))
        panel_w = max(30, int(radius * 0.18))
        panel_h = max(12, int(radius * 0.065))
        painter.drawRect(
            int(station_x - core_w / 2 - panel_w - 5), int(station_y - panel_h / 2),
            panel_w, panel_h
        )
        painter.drawRect(
            int(station_x + core_w / 2 + 5), int(station_y - panel_h / 2),
            panel_w, panel_h
        )
        painter.setPen(QPen(_rgba(highlight, 92), 0.7))
        for offset in (-29, -23, 17, 23, 29):
            painter.drawLine(int(station_x + offset), int(station_y - 5), int(station_x + offset), int(station_y + 5))

        # Navigation lights are much stronger at night; their pulse is animated.
        pulse = 0.45 + 0.55 * math.sin(self._animation_tick * 0.34)
        beacon_alpha = int((150 if self.is_daylight else 245) * max(0.25, pulse))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_rgba(highlight, beacon_alpha))
        painter.drawEllipse(int(station_x - 3), int(station_y - 31), 6, 6)
        painter.setBrush(_rgba(accent, min(255, beacon_alpha + 30)))
        painter.drawEllipse(int(station_x - ring - 3), int(station_y - 2), 5, 5)
        painter.drawEllipse(int(station_x + ring - 2), int(station_y - 2), 5, 5)

        # A moving shuttle point gives the station vignette a readable animation.
        shuttle_angle = math.radians((self._animation_tick * 4.5) % 360)
        shuttle_x = station_x + math.cos(shuttle_angle) * width * 0.18
        shuttle_y = station_y + math.sin(shuttle_angle) * height * 0.12
        painter.setBrush(_rgba(highlight, 210))
        painter.drawEllipse(int(shuttle_x - 2), int(shuttle_y - 2), 4, 4)
        painter.setPen(QPen(_rgba(accent, 88), 0.8))
        painter.drawLine(int(shuttle_x), int(shuttle_y), int(shuttle_x - 8), int(shuttle_y + 3))

    def _paint_day_night_variant(
        self,
        painter: QPainter,
        rect,
        planet_x: float,
        planet_y: float,
        planet_radius: float,
        accent: QColor,
        highlight: QColor,
        deep: QColor,
    ) -> None:
        del rect
        ellipse = QPainterPath()
        ellipse.addEllipse(
            planet_x - planet_radius,
            planet_y - planet_radius,
            planet_radius * 2,
            planet_radius * 2,
        )
        painter.save()
        painter.setClipPath(ellipse, Qt.ClipOperation.IntersectClip)

        if self.is_daylight:
            sweep = QLinearGradient(planet_x - planet_radius * 0.7, planet_y, planet_x + planet_radius * 1.0, planet_y)
            sweep.setColorAt(0.0, QColor(255, 255, 255, 0))
            sweep.setColorAt(0.42, _rgba(highlight, 28))
            sweep.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillPath(ellipse, sweep)
        else:
            shadow = QLinearGradient(planet_x - planet_radius * 0.95, planet_y, planet_x + planet_radius * 0.65, planet_y)
            shadow.setColorAt(0.0, QColor(6, 8, 14, 12))
            shadow.setColorAt(0.46, QColor(6, 8, 14, 44))
            shadow.setColorAt(0.76, QColor(3, 4, 8, 176))
            shadow.setColorAt(1.0, QColor(2, 3, 7, 205))
            painter.fillPath(ellipse, shadow)

            painter.setPen(Qt.PenStyle.NoPen)
            lights = (
                (-0.24, -0.05), (-0.14, 0.12), (-0.05, 0.04), (0.06, 0.16), (0.15, 0.02), (0.22, -0.10),
            )
            for index, (dx, dy) in enumerate(lights):
                flicker = 74 + ((self._animation_tick * 3 + index * 19) % 70)
                color = highlight if index % 2 else accent
                painter.setBrush(_rgba(color, min(165, flicker)))
                painter.drawEllipse(
                    int(planet_x + planet_radius * dx),
                    int(planet_y + planet_radius * dy),
                    2,
                    2,
                )

        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_rgba(highlight, 126 if self.is_daylight else 110), 1.25))
        painter.drawArc(
            int(planet_x - planet_radius),
            int(planet_y - planet_radius),
            int(planet_radius * 2),
            int(planet_radius * 2),
            28 * 16,
            116 * 16,
        )
        painter.setPen(QPen(_rgba(accent, 36 if self.is_daylight else 44), 0.8))
        painter.drawArc(
            int(planet_x - planet_radius * 0.87),
            int(planet_y - planet_radius * 0.35),
            int(planet_radius * 1.74),
            int(planet_radius * 0.72),
            0,
            180 * 16,
        )

        if not self.is_daylight:
            painter.setPen(QPen(_rgba(highlight, 58), 0.9))
            painter.drawArc(
                int(planet_x - planet_radius * 0.92),
                int(planet_y - planet_radius * 0.94),
                int(planet_radius * 1.90),
                int(planet_radius * 1.90),
                -10 * 16,
                62 * 16,
            )
        else:
            painter.setPen(QPen(_rgba(highlight, 42), 0.8))
            painter.drawArc(
                int(planet_x - planet_radius * 0.84),
                int(planet_y - planet_radius * 0.86),
                int(planet_radius * 1.72),
                int(planet_radius * 1.72),
                24 * 16,
                70 * 16,
            )

    def _paint_effect(self, painter: QPainter, rect, accent: QColor, highlight: QColor) -> None:
        width = float(rect.width())
        height = float(rect.height())
        effect = self.theme.effect
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if effect == "ice":
            painter.setPen(QPen(_rgba(highlight, 55), 0.8))
            for x, y in ((0.16, 0.62), (0.29, 0.73), (0.46, 0.55), (0.67, 0.69)):
                px = rect.left() + width * x
                py = rect.top() + height * y
                painter.drawLine(int(px), int(py), int(px + 3), int(py + 4))
        elif effect == "industrial":
            painter.setPen(QPen(_rgba(accent, 52), 1.0))
            for x, h in ((0.61, 0.11), (0.65, 0.16), (0.69, 0.09)):
                px = rect.left() + width * x
                bottom = rect.top() + height * 0.79
                painter.drawLine(int(px), int(bottom), int(px), int(bottom - height * h))
        elif effect == "city":
            painter.setPen(Qt.PenStyle.NoPen)
            for x, y, color in (
                (0.60, 0.66, accent),
                (0.64, 0.72, highlight),
                (0.69, 0.61, accent),
                (0.73, 0.70, highlight),
            ):
                painter.setBrush(_rgba(color, 65))
                painter.drawRect(int(rect.left() + width * x), int(rect.top() + height * y), 2, 3)
        elif effect == "gas":
            painter.setPen(QPen(_rgba(highlight, 35), 1.1))
            for y in (0.62, 0.70):
                cloud = QPainterPath()
                cloud.moveTo(rect.left() + width * 0.57, rect.top() + height * y)
                cloud.cubicTo(
                    rect.left() + width * 0.66,
                    rect.top() + height * (y - 0.06),
                    rect.left() + width * 0.77,
                    rect.top() + height * (y + 0.05),
                    rect.left() + width * 0.90,
                    rect.top() + height * (y - 0.01),
                )
                painter.drawPath(cloud)
        elif effect in {"desert", "heat"}:
            painter.setPen(QPen(_rgba(accent, 42), 0.9))
            for y in (0.72, 0.78):
                painter.drawArc(
                    int(rect.left() + width * 0.54),
                    int(rect.top() + height * y),
                    int(width * 0.39),
                    int(height * 0.12),
                    0,
                    180 * 16,
                )
        elif effect == "mist":
            haze = QLinearGradient(rect.left() + width * 0.45, 0, rect.right(), 0)
            haze.setColorAt(0.0, QColor(255, 255, 255, 0))
            haze.setColorAt(1.0, _rgba(highlight, 23))
            painter.fillRect(rect, haze)
        elif effect == "orbit":
            painter.setPen(QPen(_rgba(accent, 42), 0.7))
            painter.drawEllipse(
                int(rect.left() + width * 0.70),
                int(rect.top() + height * 0.45),
                int(width * 0.20),
                int(height * 0.16),
            )

    def _paint_weather_background(
        self,
        painter: QPainter,
        rect,
        planet_x: float,
        planet_y: float,
        planet_radius: float,
        accent: QColor,
        highlight: QColor,
        deep: QColor,
    ) -> None:
        """Paint large sun/cloud masses behind the planet."""
        width = float(rect.width())
        height = float(rect.height())
        tick = self._animation_tick

        if self.weather_key == "sunny":
            pulse = 0.94 + 0.06 * math.sin(tick * 0.16)
            sun_radius = min(width, height) * 0.34 * pulse
            sun_x = min(rect.right() - sun_radius * 0.70, planet_x - planet_radius * 0.24)
            sun_y = rect.top() + height * 0.24
            glow = QRadialGradient(sun_x, sun_y, sun_radius * 1.72)
            glow.setColorAt(0.0, _rgba(highlight, 220 if self.is_daylight else 105))
            glow.setColorAt(0.22, _rgba(accent, 158 if self.is_daylight else 72))
            glow.setColorAt(0.58, _rgba(accent, 46 if self.is_daylight else 20))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(
                int(sun_x - sun_radius * 1.72), int(sun_y - sun_radius * 1.72),
                int(sun_radius * 3.44), int(sun_radius * 3.44),
            )
            painter.setBrush(_rgba(highlight, 172 if self.is_daylight else 76))
            painter.drawEllipse(
                int(sun_x - sun_radius), int(sun_y - sun_radius),
                int(sun_radius * 2), int(sun_radius * 2),
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_rgba(highlight, 78 if self.is_daylight else 34), 1.25))
            rotation = math.radians((tick * 2.0) % 360)
            for index in range(10):
                angle = rotation + math.radians(index * 36)
                inner = sun_radius * 1.10
                outer = sun_radius * (1.40 + 0.08 * (index % 2))
                painter.drawLine(
                    int(sun_x + math.cos(angle) * inner),
                    int(sun_y + math.sin(angle) * inner),
                    int(sun_x + math.cos(angle) * outer),
                    int(sun_y + math.sin(angle) * outer),
                )
            return

        if self.weather_key not in {"rain", "snow", "storm", "tempest"}:
            return

        # A broad moving cloud bank sits behind the upper half of the planet.
        drift = math.sin(tick * 0.065) * width * 0.025
        cloud_x = planet_x - planet_radius * 0.30 + drift
        cloud_y = rect.top() + height * 0.26
        cloud_width = min(width * 0.60, planet_radius * 1.48)
        cloud_height = height * (0.30 if self.weather_key in {"storm", "tempest"} else 0.25)
        cloud_color = QColor(deep)
        cloud_color = cloud_color.lighter(122 if self.is_daylight else 104)
        base_alpha = 142 if self.weather_key in {"storm", "tempest"} else 108
        if not self.is_daylight:
            base_alpha += 24

        cloud_glow = QRadialGradient(cloud_x, cloud_y, cloud_width * 0.72)
        cloud_glow.setColorAt(0.0, _rgba(highlight, 42 if self.is_daylight else 24))
        cloud_glow.setColorAt(0.42, _rgba(cloud_color, base_alpha))
        cloud_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(cloud_glow)
        painter.drawEllipse(
            int(cloud_x - cloud_width * 0.72), int(cloud_y - cloud_height * 1.35),
            int(cloud_width * 1.44), int(cloud_height * 2.70),
        )
        painter.setBrush(_rgba(cloud_color, base_alpha))
        lobes = (
            (-0.34, 0.10, 0.34),
            (-0.12, -0.05, 0.42),
            (0.15, -0.01, 0.38),
            (0.37, 0.12, 0.29),
        )
        for dx, dy, size in lobes:
            lobe_w = cloud_width * size
            lobe_h = cloud_height * (0.78 + size * 0.36)
            painter.drawEllipse(
                int(cloud_x + cloud_width * dx - lobe_w / 2),
                int(cloud_y + cloud_height * dy - lobe_h / 2),
                int(lobe_w), int(lobe_h),
            )
        painter.drawRoundedRect(
            int(cloud_x - cloud_width * 0.43), int(cloud_y),
            int(cloud_width * 0.86), int(cloud_height * 0.42),
            int(cloud_height * 0.18), int(cloud_height * 0.18),
        )

    def _paint_weather_foreground(
        self,
        painter: QPainter,
        rect,
        accent: QColor,
        highlight: QColor,
        deep: QColor,
    ) -> None:
        """Paint precipitation and effects in front of the planet."""
        width = float(rect.width())
        height = float(rect.height())
        tick = self._animation_tick
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.weather_key == "rain":
            painter.setPen(QPen(_rgba(highlight, 126), 1.15))
            shift = (tick * 4) % 24
            for index in range(18):
                x = rect.left() + width * (0.47 + (index % 9) * 0.057)
                y = rect.top() + height * (0.25 + ((index * 13 + shift) % 58) / 100.0)
                length = 10 + (index % 3) * 3
                painter.drawLine(int(x), int(y), int(x - 5), int(y + length))
        elif self.weather_key == "snow":
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(18):
                drift = math.sin((tick + index * 11) * 0.12) * 6.0
                x = rect.left() + width * (0.46 + (index % 9) * 0.058) + drift
                y = rect.top() + height * (0.22 + ((index * 13 + tick * 2) % 66) / 100.0)
                size = 2 + (index % 3)
                painter.setBrush(_rgba(highlight, 95 + (index % 3) * 28))
                painter.drawEllipse(int(x), int(y), size, size)
        elif self.weather_key == "storm":
            flash = 75 + int(105 * max(0.0, math.sin(tick * 0.38)) ** 9)
            painter.setPen(QPen(_rgba(highlight, flash), 1.8))
            bolt = QPainterPath()
            bolt.moveTo(rect.left() + width * 0.73, rect.top() + height * 0.24)
            bolt.lineTo(rect.left() + width * 0.66, rect.top() + height * 0.45)
            bolt.lineTo(rect.left() + width * 0.72, rect.top() + height * 0.45)
            bolt.lineTo(rect.left() + width * 0.64, rect.top() + height * 0.70)
            painter.drawPath(bolt)
            painter.setPen(QPen(_rgba(accent, 110), 1.0))
            shift = (tick * 5) % 28
            for index in range(11):
                x = rect.left() + width * (0.50 + (index % 7) * 0.066)
                y = rect.top() + height * (0.31 + ((index * 17 + shift) % 52) / 100.0)
                painter.drawLine(int(x), int(y), int(x - 5), int(y + 13))
        elif self.weather_key == "tempest":
            painter.setPen(QPen(_rgba(highlight, 92), 1.25))
            for index, scale in enumerate((1.0, 0.72, 0.48)):
                size_w = width * 0.37 * scale
                size_h = height * 0.30 * scale
                x = rect.left() + width * 0.70 - size_w / 2
                y = rect.top() + height * 0.48 - size_h / 2
                painter.drawArc(
                    int(x), int(y), int(size_w), int(size_h),
                    int(((tick * (7 + index * 2)) + index * 80) % 5760),
                    218 * 16,
                )
            painter.setPen(QPen(_rgba(accent, 88), 1.0))
            shift = (tick * 5) % 25
            for index in range(13):
                x = rect.left() + width * (0.46 + (index % 8) * 0.061)
                y = rect.top() + height * (0.33 + ((index * 19 + shift) % 48) / 100.0)
                painter.drawLine(int(x), int(y), int(x - 8), int(y + 10))
        elif self.weather_key == "air_bad":
            pulse = (tick % 36) / 36.0
            haze = QLinearGradient(rect.left() + width * (0.38 + pulse * 0.04), rect.top(), rect.right(), rect.bottom())
            haze.setColorAt(0.0, QColor(255, 255, 255, 0))
            haze.setColorAt(0.44, _rgba(accent, 34 + int(pulse * 18)))
            haze.setColorAt(1.0, _rgba(deep, 68 + int(pulse * 18)))
            painter.fillRect(rect, haze)
            painter.setPen(QPen(_rgba(highlight, 35 + int(pulse * 20)), 1.1))
            drift = ((tick % 24) - 12) * 0.70
            for index, y in enumerate((0.50, 0.62, 0.73, 0.82)):
                offset = drift * (1.0 if index % 2 == 0 else -0.65)
                painter.drawLine(
                    int(rect.left() + width * 0.43 + offset),
                    int(rect.top() + height * y),
                    int(rect.left() + width * 0.96 + offset),
                    int(rect.top() + height * y),
                )


class FadingMarqueeLabel(QWidget):
    """Single-line text with edge fades and a slow occasional reveal."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = str(text)
        self._offset = 0.0
        self._phase = "wait"
        self._elapsed_ms = 0
        self._text_color = QColor("white")
        self._alignment = Qt.AlignmentFlag.AlignLeft
        self._viewport_start = 0
        self._viewport_width: int | None = None
        self.setMinimumHeight(11)
        self.setMaximumHeight(14)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._advance)
        self.timer.start()

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802
        value = " ".join(str(text or "").split())
        if value == self._text:
            return
        self._text = value
        self._offset = 0.0
        self._phase = "wait"
        self._elapsed_ms = 0
        self.setToolTip(value)
        self.update()

    def set_text_color(self, color: QColor) -> None:
        self._text_color = QColor(color)
        self.update()

    def setAlignment(self, alignment: Qt.AlignmentFlag) -> None:  # noqa: N802
        self._alignment = alignment
        self.update()

    def alignment(self) -> Qt.AlignmentFlag:
        return self._alignment

    def set_viewport(self, start: int, width: int | None) -> None:
        viewport_start = max(0, min(max(0, self.width() - 1), int(start)))
        value = (
            None
            if width is None
            else max(1, min(self.width() - viewport_start, int(width)))
        )
        if viewport_start == self._viewport_start and value == self._viewport_width:
            return
        self._viewport_start = viewport_start
        self._viewport_width = value
        self._offset = 0.0
        self._phase = "wait"
        self._elapsed_ms = 0
        self.update()

    def set_viewport_width(self, width: int | None) -> None:
        self.set_viewport(0, width)

    def _paint_width(self) -> int:
        return max(1, min(self.width() - self._viewport_start, self._viewport_width or self.width()))

    def _max_offset(self) -> float:
        return max(0.0, float(self.fontMetrics().horizontalAdvance(self._text) - max(1, self._paint_width() - 4)))

    def _advance(self) -> None:
        maximum = self._max_offset()
        if not self.isVisible() or maximum <= 0.5:
            if self._offset:
                self._offset = 0.0
                self.update()
            self._phase = "wait"
            self._elapsed_ms = 0
            return
        self._elapsed_ms += self.timer.interval()
        if self._phase == "wait":
            if self._elapsed_ms >= 4_500:
                self._phase = "scroll"
                self._elapsed_ms = 0
        elif self._phase == "scroll":
            self._offset = min(maximum, self._offset + 0.72)
            self.update()
            if self._offset >= maximum:
                self._phase = "end"
                self._elapsed_ms = 0
        elif self._phase == "end":
            if self._elapsed_ms >= 1_700:
                self._offset = 0.0
                self._phase = "rest"
                self._elapsed_ms = 0
                self.update()
        elif self._phase == "rest" and self._elapsed_ms >= 6_500:
            self._phase = "scroll"
            self._elapsed_ms = 0

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if not self._text or self.width() <= 1 or self.height() <= 1:
            return
        image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        painter.setPen(self._text_color)
        baseline = (self.height() + self.fontMetrics().ascent() - self.fontMetrics().descent()) / 2.0
        maximum = self._max_offset()
        paint_width = self._paint_width()
        paint_start = self._viewport_start
        painter.setClipRect(paint_start, 0, paint_width, self.height())
        if maximum <= 0.5 and self._alignment & Qt.AlignmentFlag.AlignRight:
            text_width = self.fontMetrics().horizontalAdvance(self._text)
            draw_x = max(paint_start + 2, paint_start + paint_width - text_width - 2)
        else:
            draw_x = int(paint_start + 2 - self._offset)
        painter.drawText(int(draw_x), int(baseline), self._text)
        if maximum > 0.5:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            fade = min(16.0, max(7.0, paint_width * 0.07))
            gradient = QLinearGradient(paint_start, 0, paint_start + paint_width, 0)
            left_alpha = 255 if self._offset < 0.5 else 0
            right_alpha = 255 if self._offset >= maximum - 0.5 else 0
            gradient.setColorAt(0.0, QColor(255, 255, 255, left_alpha))
            gradient.setColorAt(min(0.49, fade / max(1.0, paint_width)), QColor(255, 255, 255, 255))
            gradient.setColorAt(max(0.51, 1.0 - fade / max(1.0, paint_width)), QColor(255, 255, 255, 255))
            gradient.setColorAt(1.0, QColor(255, 255, 255, right_alpha))
            painter.fillRect(paint_start, 0, paint_width, self.height(), gradient)
        painter.end()
        output = QPainter(self)
        output.drawImage(0, 0, image)


class HudClipContainer(QWidget):
    """Crop and uniformly scale one independent HUD group."""

    _UNBOUNDED = 16_777_215

    def __init__(
        self,
        content: QWidget,
        native_width: int,
        height: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.content = content
        self.native_width = max(1, int(native_width))
        self.native_height = max(1, int(height))
        self.crop_left = 0
        self.crop_right = 0
        self.scale_percent = 100
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.content.setParent(self)
        self.content.setFixedSize(self.native_width, self.native_height)
        self.content.show()
        self._widget_states: list[dict[str, object]] = []
        self._layout_states: list[dict[str, object]] = []
        self._capture_geometry_baseline()
        self.set_transform(0, 0, 100)

    @property
    def visible_width(self) -> int:
        return max(1, self.native_width - self.crop_left - self.crop_right)

    @property
    def displayed_width(self) -> int:
        return max(1, int(round(self.visible_width * self.scale_percent / 100.0)))

    @property
    def displayed_height(self) -> int:
        return max(1, int(round(self.native_height * self.scale_percent / 100.0)))

    def _capture_geometry_baseline(self) -> None:
        self.content.layout().activate() if self.content.layout() is not None else None
        widgets = [self.content, *self.content.findChildren(QWidget)]
        self._widget_states = []
        for widget in widgets:
            font = QFont(widget.font())
            icon_size = widget.iconSize() if hasattr(widget, "iconSize") else None
            self._widget_states.append(
                {
                    "widget": widget,
                    "minimum_width": widget.minimumWidth(),
                    "minimum_height": widget.minimumHeight(),
                    "maximum_width": widget.maximumWidth(),
                    "maximum_height": widget.maximumHeight(),
                    "font": font,
                    "icon_size": icon_size,
                }
            )

        self._layout_states = []
        seen: set[int] = set()
        for widget in widgets:
            layout = widget.layout()
            if layout is None or id(layout) in seen:
                continue
            seen.add(id(layout))
            margins = layout.contentsMargins()
            state: dict[str, object] = {
                "layout": layout,
                "margins": (margins.left(), margins.top(), margins.right(), margins.bottom()),
                "spacing": layout.spacing(),
            }
            if hasattr(layout, "horizontalSpacing"):
                state["horizontal_spacing"] = layout.horizontalSpacing()
            if hasattr(layout, "verticalSpacing"):
                state["vertical_spacing"] = layout.verticalSpacing()
            self._layout_states.append(state)

    def refresh_font_baseline(self) -> None:
        """Capture fonts after project typography has been applied."""
        for state in self._widget_states:
            widget = state["widget"]
            state["font"] = QFont(widget.font())

    @staticmethod
    def _scaled_metric(value: int, scale: float, *, unbounded: bool = False) -> int:
        if unbounded and value >= HudClipContainer._UNBOUNDED:
            return HudClipContainer._UNBOUNDED
        if value <= 0:
            return 0
        return max(1, int(round(value * scale)))

    def _apply_uniform_scale(self, percent: int) -> None:
        percent = max(50, min(200, int(percent)))
        scale = percent / 100.0
        self.scale_percent = percent

        for state in self._layout_states:
            layout = state["layout"]
            left, top, right, bottom = state["margins"]
            layout.setContentsMargins(
                self._scaled_metric(left, scale),
                self._scaled_metric(top, scale),
                self._scaled_metric(right, scale),
                self._scaled_metric(bottom, scale),
            )
            spacing = int(state["spacing"])
            if spacing >= 0:
                layout.setSpacing(self._scaled_metric(spacing, scale))
            horizontal = int(state.get("horizontal_spacing", -1))
            vertical = int(state.get("vertical_spacing", -1))
            if horizontal >= 0 and hasattr(layout, "setHorizontalSpacing"):
                layout.setHorizontalSpacing(self._scaled_metric(horizontal, scale))
            if vertical >= 0 and hasattr(layout, "setVerticalSpacing"):
                layout.setVerticalSpacing(self._scaled_metric(vertical, scale))

        for state in self._widget_states:
            widget = state["widget"]
            minimum_width = self._scaled_metric(int(state["minimum_width"]), scale)
            minimum_height = self._scaled_metric(int(state["minimum_height"]), scale)
            maximum_width = self._scaled_metric(
                int(state["maximum_width"]), scale, unbounded=True
            )
            maximum_height = self._scaled_metric(
                int(state["maximum_height"]), scale, unbounded=True
            )
            widget.setMinimumSize(minimum_width, minimum_height)
            widget.setMaximumSize(maximum_width, maximum_height)

            font = QFont(state["font"])
            if font.pointSizeF() > 0:
                font.setPointSizeF(max(1.0, font.pointSizeF() * scale))
            elif font.pixelSize() > 0:
                font.setPixelSize(max(1, int(round(font.pixelSize() * scale))))
            widget.setFont(font)

            if hasattr(widget, "setIconSize") and state["icon_size"] is not None:
                icon_size = state["icon_size"]
                widget.setIconSize(
                    icon_size.__class__(
                        max(1, int(round(icon_size.width() * scale))),
                        max(1, int(round(icon_size.height() * scale))),
                    )
                )

        self.content.setFixedSize(
            max(1, int(round(self.native_width * scale))),
            max(1, int(round(self.native_height * scale))),
        )
        for state in self._layout_states:
            layout = state["layout"]
            layout.invalidate()
            layout.activate()

    def set_transform(self, left: int, right: int, scale_percent: int) -> None:
        maximum_total = max(0, self.native_width - 1)
        left = max(0, min(maximum_total, int(left)))
        right = max(0, min(maximum_total - left, int(right)))
        self.crop_left = left
        self.crop_right = right
        self._apply_uniform_scale(scale_percent)
        visible = self.displayed_width
        self.setFixedSize(visible, self.displayed_height)

        gradient = QLinearGradient(0, 0, visible, 0)
        left_fade = min(14.0, max(6.0, visible * 0.18)) if left else 0.0
        right_fade = min(14.0, max(6.0, visible * 0.18)) if right else 0.0
        if not left and not right:
            gradient.setColorAt(0.0, QColor(255, 255, 255, 255))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 255))
        else:
            if left:
                gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
                gradient.setColorAt(
                    min(0.48, left_fade / max(1.0, visible)),
                    QColor(255, 255, 255, 255),
                )
            else:
                gradient.setColorAt(0.0, QColor(255, 255, 255, 255))
            if right:
                gradient.setColorAt(
                    max(0.52, 1.0 - right_fade / max(1.0, visible)),
                    QColor(255, 255, 255, 255),
                )
                gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            else:
                gradient.setColorAt(1.0, QColor(255, 255, 255, 255))
        self._effect.setOpacityMask(QBrush(gradient))
        scaled_left = int(round(self.crop_left * self.scale_percent / 100.0))
        self.content.move(-scaled_left, 0)
        self.content.raise_()
        self.show()

    def set_crop(self, left: int, right: int) -> None:
        self.set_transform(left, right, self.scale_percent)

    def set_scale_percent(self, percent: int) -> None:
        self.set_transform(self.crop_left, self.crop_right, percent)

    def set_visible_width(self, width: int) -> None:
        visible = max(1, min(self.native_width, int(width)))
        self.set_transform(0, self.native_width - visible, self.scale_percent)



class HudGuideLine(QWidget):
    """One movable cyan HUD guide, kept independent from the content blocks."""

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.side = "right" if str(side).strip().casefold() == "right" else "left"
        self._accent = QColor(70, 201, 242)
        self._highlight = QColor(99, 227, 255)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_theme(self, accent: QColor, highlight: QColor) -> None:
        self._accent = QColor(accent)
        self._highlight = QColor(highlight)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if self.width() <= 2 or self.height() <= 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        rect = self.rect().adjusted(1, 1, -1, -1)
        y = float(rect.bottom()) - 1.0
        shoulder = max(24.0, min(54.0, rect.width() * 0.23))
        bend = min(24.0, max(12.0, rect.width() * 0.12))
        path = QPainterPath()
        if self.side == "left":
            path.moveTo(float(rect.left()), y - 8.0)
            path.lineTo(float(rect.left()) + shoulder, y - 7.0)
            path.lineTo(float(rect.left()) + shoulder + bend, y)
            path.lineTo(float(rect.right()), y)
        else:
            path.moveTo(float(rect.left()), y)
            path.lineTo(float(rect.right()) - shoulder - bend, y)
            path.lineTo(float(rect.right()) - shoulder, y - 7.0)
            path.lineTo(float(rect.right()), y - 8.0)

        gradient = QLinearGradient(float(rect.left()), y, float(rect.right()), y)
        peak = int(255 * 0.85)
        accent = QColor(self._accent)
        highlight = QColor(self._highlight)
        accent.setAlpha(int(peak * 0.20))
        medium = QColor(self._accent)
        medium.setAlpha(int(peak * 0.66))
        highlight.setAlpha(peak)
        gradient.setColorAt(0.0, accent)
        gradient.setColorAt(0.20, medium)
        gradient.setColorAt(0.52, highlight)
        gradient.setColorAt(0.82, medium)
        gradient.setColorAt(1.0, accent)
        brush = QBrush(gradient)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                brush,
                1.35,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setOpacity(0.18)
        painter.drawPath(path)
        painter.setPen(
            QPen(
                brush,
                0.70,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setOpacity(1.0)
        painter.drawPath(path)
        painter.end()


class LocationCaptureButton(QPushButton):
    """Small Wi-Fi button that writes one Public Real Time Checker registry record."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setObjectName("mediaButton")
        self.setFixedSize(18, 18)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        label = tr(
            self.settings,
            "Enregistrer le lieu et le code Game.log",
            "Save place and Game.log code",
        )
        self.setToolTip(label)
        self.setAccessibleName(label)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().buttonText().color()
        color.setAlpha(225 if self.isEnabled() else 100)
        painter.setPen(QPen(color, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        center_x = self.width() / 2.0
        base_y = self.height() * 0.72
        for radius in (4.0, 7.0):
            rect = QRectF(center_x - radius, base_y - radius, radius * 2.0, radius * 2.0)
            painter.drawArc(rect, 42 * 16, 96 * 16)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(center_x, base_y + 0.5), 1.35, 1.35)
        painter.end()


class CompanionWidgetPage(QWidget):
    mode_requested = Signal(bool)
    close_requested = Signal()
    settings_requested = Signal()
    location_capture_requested = Signal()
    hud_region_changed = Signal(object)

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.language = current_language(settings)
        self._compact = False
        self._lite_mode = False
        self._playable: list[RadioStation] = []
        self._detected_location_name: str | None = None
        self._detected_location_body: str | None = None
        self._detected_location_raw: str | None = None
        self._detected_location_type: str = ""
        self._detected_clock_mode: str = "local"
        self._detected_travel_state: str = "location"
        self._detected_jurisdiction: str = ""
        self._detected_monitored_state: str = "unknown"
        self._manual_location_override = False

        self.engine = RadioEngine(
            self.settings.value("radio/volume", 35, type=int),
            self,
            self.settings.value("radio/output_device", "", type=str),
        )
        self.engine.state_changed.connect(self._on_audio_state)
        self.engine.error.connect(self._on_audio_error)
        self.engine.track_changed.connect(self._on_track_changed)
        self.engine.metadata_status_changed.connect(self._on_metadata_status)

        self.card = SpaceCard()
        hud_primary = normalize_hud_color(
            self.settings.value(HUD_COLOR_SETTINGS_KEY, DEFAULT_HUD_COLOR, type=str)
        )
        saved_secondary = self.settings.value(
            HUD_SECONDARY_COLOR_SETTINGS_KEY, "", type=str
        ).strip()
        hud_secondary = (
            normalize_hud_secondary_color(saved_secondary)
            if saved_secondary
            else hud_theme_colors(hud_primary)[1]
        )
        self.card.set_hud_colors(hud_primary, hud_secondary)
        self.card.set_hud_strip_mode(True)
        # The original card-wide lines do not scale to a full-screen canvas.
        # Dedicated movable guide elements render them instead.
        self.card.set_hud_bars_visible(False)
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(0, 1, 0, 0)
        self.card_layout.setSpacing(0)

        # Selection stays in Settings. The widget exposes no selection control.
        self.location_combo = QComboBox(self)
        self.location_combo.setObjectName("widgetLocationComboInternal")
        for location in VERSE_LOCATIONS:
            self.location_combo.addItem(location.label.upper(), location.location_id)
        saved_location = self.settings.value("verse_time/location", "", type=str)
        if not saved_location:
            saved_location = self.settings.value("verse_weather/location", "new-babbage", type=str)
        saved_location = normalize_location_id(saved_location)
        self.location_combo.setCurrentIndex(max(0, self.location_combo.findData(saved_location)))
        self.location_combo.currentIndexChanged.connect(self.refresh_time)
        self.location_combo.hide()


        self.minimal_time_label = QLabel("--:--")
        self.minimal_time_label.setObjectName("widgetMinimalTime")
        self.minimal_time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.minimal_time_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.minimal_time_label.setFixedHeight(31)

        self.minimal_pc_time_label = QLabel("--:--")
        self.minimal_pc_time_label.setObjectName("widgetMinimalPcTime")
        self.minimal_pc_time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.minimal_pc_time_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.minimal_pc_time_label.setFixedHeight(23)
        self.minimal_pc_time_label.setToolTip(tr(self.settings, "Heure réelle du PC", "Real PC time"))

        self.minimal_weather_label = QLabel("")
        self.minimal_weather_label.setObjectName("widgetMinimalWeather")
        self.minimal_weather_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.minimal_weather_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.minimal_weather_label.setFixedHeight(15)

        self.time_label = QLabel("--:--")
        self.time_label.setObjectName("widgetTemperature")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.time_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.time_label.setFixedHeight(31)

        self.pc_time_label = QLabel("--:--")
        self.pc_time_label.setObjectName("widgetPcTime")
        self.pc_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.pc_time_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pc_time_label.setFixedHeight(12)
        self.pc_time_label.setToolTip(tr(self.settings, "Heure réelle du PC", "Real PC time"))

        self.city_label = FadingMarqueeLabel("")
        self.city_label.setObjectName("widgetCityLabel")
        self.city_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.city_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.city_label.setFixedHeight(15)

        self.radio_station_label = FadingMarqueeLabel("")
        self.radio_station_label.setObjectName("widgetStationName")
        self.radio_station_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.radio_station_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.radio_station_label.setFixedHeight(15)

        self.condition_label = QLabel(tr(self.settings, "Calcul météo", "Calculating weather"))
        self.condition_label.setObjectName("widgetCondition")
        self.condition_label.setWordWrap(False)
        self.condition_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.condition_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.condition_label.setFixedHeight(9)

        self.location_capture_button = LocationCaptureButton(self.settings, self)
        self.location_capture_button.clicked.connect(self.location_capture_requested)

        self.mode_switch = AppleSwitch()
        self.mode_switch.setFixedSize(28, 16)
        self.mode_switch.setChecked(True)
        self.mode_switch.toggled.connect(self.mode_requested)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("widgetCloseButton")
        self.close_button.setFixedSize(18, 18)
        self.close_button.setToolTip(tr(self.settings, "Fermer toute l'application", "Close the entire application"))
        self.close_button.clicked.connect(self.close_requested)

        # Keep the 548 × 78 px window, but use two compact 204 px edge blocks
        # separated by a genuine 140 px neutral centre, as in the reference HUD.
        self.top_layout = QHBoxLayout()
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(1)
        self.top_layout.addWidget(self.close_button)
        self.top_layout.addWidget(self.location_capture_button)
        self.top_layout.addWidget(self.mode_switch)
        self.top_controls_box = QWidget(self.card)
        self.top_controls_box.setObjectName("widgetTopControls")
        self.top_controls_box.setFixedWidth(66)
        self.top_controls_box.setLayout(self.top_layout)

        self.location_text_box = QWidget(self.card)
        self.location_text_box.setObjectName("widgetLocationTextBox")
        self.location_text_box.setFixedSize(52, 15)
        self.location_text_layout = QVBoxLayout(self.location_text_box)
        self.location_text_layout.setContentsMargins(0, 0, 0, 0)
        self.location_text_layout.setSpacing(0)
        self.location_text_layout.addWidget(self.city_label)
        self.condition_label.setParent(self.location_text_box)
        self.condition_label.hide()

        # The Windows clock is an independent HUD block. It can now be moved,
        # cropped, scaled or grouped without moving the location name.
        self.pc_time_box = QWidget(self.card)
        self.pc_time_box.setObjectName("widgetPcTimeBox")
        self.pc_time_box.setFixedSize(52, 12)
        self.pc_time_layout = QHBoxLayout(self.pc_time_box)
        self.pc_time_layout.setContentsMargins(0, 0, 0, 0)
        self.pc_time_layout.setSpacing(0)
        self.pc_time_layout.addWidget(self.pc_time_label)

        self.time_text_box = QWidget(self.card)
        self.time_text_box.setObjectName("widgetClockZone")
        self.time_text_box.setFixedWidth(84)
        self.time_text_layout = QVBoxLayout(self.time_text_box)
        self.time_text_layout.setContentsMargins(0, 0, 0, 0)
        self.time_text_layout.setSpacing(0)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.time_label.setFixedWidth(84)
        self.time_text_layout.addWidget(self.time_label)

        # Compatibility aliases retained for tests and integrations.
        self.time_row_layout = self.time_text_layout
        self.expanded_header_layout = QGridLayout()

        self.left_zone = QWidget(self.card)
        self.left_zone.setObjectName("widgetLeftZone")
        self.left_zone.setFixedWidth(204)
        self.left_zone_layout = QHBoxLayout(self.left_zone)
        self.left_zone_layout.setContentsMargins(0, 0, 0, 0)
        self.left_zone_layout.setSpacing(1)
        self.left_zone_layout.addWidget(
            self.top_controls_box, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.left_zone_layout.addWidget(
            self.location_text_box, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.left_zone_layout.addWidget(
            self.time_text_box, 0, Qt.AlignmentFlag.AlignVCenter
        )

        self.station_combo = QComboBox(self)
        self.station_combo.setObjectName("widgetStationComboInternal")
        self.station_combo.currentIndexChanged.connect(self._on_station_changed)
        self.station_combo.hide()

        self.track_label = FadingMarqueeLabel(tr(self.settings, "Connexion aux métadonnées radio…", "Connecting to radio metadata…"))
        self.track_label.setObjectName("widgetTrack")
        self.track_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.track_label.setFixedHeight(15)
        self.track_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.previous_button = self._media_button("◀◀", tr(self.settings, "Station précédente · commande multimédia Fn", "Previous station · Fn media command"))
        self.play_button = self._media_button("▶", tr(self.settings, "Lecture / pause · commande multimédia Fn", "Play / pause · Fn media command"))
        self.next_button = self._media_button("▶▶", tr(self.settings, "Station suivante · commande multimédia Fn", "Next station · Fn media command"))
        self.previous_button.clicked.connect(lambda: self.change_station(-1))
        self.next_button.clicked.connect(lambda: self.change_station(1))
        self.play_button.clicked.connect(self.toggle_playback)

        self.media_row = QHBoxLayout()
        self.media_row.setContentsMargins(0, 0, 0, 0)
        self.media_row.setSpacing(1)
        self.media_row.addWidget(self.previous_button)
        self.media_row.addWidget(self.play_button)
        self.media_row.addWidget(self.next_button)
        self.media_controls_box = QWidget(self.card)
        self.media_controls_box.setObjectName("widgetMediaControls")
        self.media_controls_box.setFixedWidth(56)
        self.media_controls_box.setLayout(self.media_row)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("widgetVolume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(46)
        self.volume_slider.setValue(self.settings.value("radio/volume", 35, type=int))
        self.volume_slider.setToolTip(f"{tr(self.settings, 'Volume', 'Volume')} : {self.volume_slider.value()}%")
        self.volume_slider.valueChanged.connect(self.change_volume)

        # Keep the compact 147 px top row for the station and volume. The
        # artist/title line is separate and spans the complete 204 px radio
        # block, including the horizontal area directly below the media buttons.
        self.radio_info_box = QWidget(self.card)
        self.radio_info_box.setObjectName("widgetRadioInfoBox")
        self.radio_info_box.setFixedWidth(147)
        self.radio_info_layout = QHBoxLayout(self.radio_info_box)
        self.radio_info_layout.setContentsMargins(0, 0, 0, 0)
        self.radio_info_layout.setSpacing(2)
        self.radio_info_layout.addWidget(self.radio_station_label, 1)
        self.radio_info_layout.addWidget(self.volume_slider, 0)
        # Compatibility alias retained for tests and integrations.
        self.radio_top_layout = self.radio_info_layout

        self.radio_box = QWidget(self.card)
        self.radio_box.setObjectName("widgetRightZone")
        self.radio_box.setFixedWidth(204)
        self.radio_layout = QGridLayout(self.radio_box)
        self.radio_layout.setContentsMargins(0, 0, 0, 0)
        self.radio_layout.setHorizontalSpacing(1)
        self.radio_layout.setVerticalSpacing(0)
        self.radio_layout.addWidget(self.radio_info_box, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        self.radio_layout.addWidget(self.media_controls_box, 0, 1, Qt.AlignmentFlag.AlignVCenter)
        self.radio_layout.addWidget(self.track_label, 1, 0, 1, 2)
        self.radio_layout.setColumnStretch(0, 0)
        self.radio_layout.setColumnStretch(1, 0)

        self.center_gap = QWidget(self.card)
        self.center_gap.setObjectName("widgetNeutralCenterGap")
        self.center_gap.setFixedWidth(140)
        self.center_gap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.guide_left = HudGuideLine("left", self.card)
        self.guide_left.setObjectName("widgetHudGuideLeft")
        self.guide_right = HudGuideLine("right", self.card)
        self.guide_right.setObjectName("widgetHudGuideRight")

        self.expanded_panel = QWidget(self.card)
        self.expanded_panel.setObjectName("widgetExpandedHudPanel")
        self.hud_row = QHBoxLayout(self.expanded_panel)
        self.hud_row.setContentsMargins(0, 4, 0, 0)
        self.hud_row.setSpacing(0)
        self.hud_row.addWidget(self.left_zone, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hud_row.addWidget(self.center_gap, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hud_row.addWidget(self.radio_box, 0, Qt.AlignmentFlag.AlignVCenter)
        self.card_layout.addWidget(self.expanded_panel, 1)
        self.card_layout.addSpacing(12)
        self._hud_layout_preview: dict[str, tuple[int, int]] | None = None
        self._hud_crop_preview: dict[str, dict[str, int]] | None = None
        self._hud_scale_preview: dict[str, int] | None = None
        self._hud_text_alignment_preview: dict[str, str] | None = None
        self._hud_canvas_width = HUD_CANVAS_WIDTH
        self._hud_canvas_height = HUD_CANVAS_HEIGHT
        self._hud_clip_frames: dict[str, HudClipContainer] = {}
        self._detach_expanded_hud_elements()

        self.minimal_panel = QWidget(self.card)
        self.minimal_panel.setObjectName("widgetMinimalPanel")
        self.minimal_panel_layout = QHBoxLayout(self.minimal_panel)
        self.minimal_panel_layout.setContentsMargins(2, 0, 1, 0)
        self.minimal_panel_layout.setSpacing(5)

        self.minimal_text_box = QWidget(self.minimal_panel)
        self.minimal_text_layout = QVBoxLayout(self.minimal_text_box)
        self.minimal_text_layout.setContentsMargins(0, 0, 0, 0)
        self.minimal_text_layout.setSpacing(0)
        self.minimal_clock_layout = QHBoxLayout()
        self.minimal_clock_layout.setContentsMargins(0, 0, 0, 0)
        self.minimal_clock_layout.setSpacing(5)
        self.minimal_clock_layout.addWidget(self.minimal_time_label)
        self.minimal_clock_layout.addWidget(
            self.minimal_pc_time_label, 0, Qt.AlignmentFlag.AlignBottom
        )
        self.minimal_clock_layout.addStretch(1)
        self.minimal_text_layout.addLayout(self.minimal_clock_layout)
        # The compact line shows the selected station instead of simulated weather.
        self.minimal_text_layout.addWidget(self.minimal_weather_label)
        self.minimal_track_label = FadingMarqueeLabel(tr(self.settings, "Connexion aux métadonnées radio…", "Connecting to radio metadata…"))
        self.minimal_track_label.setObjectName("widgetMinimalTrack")
        self.minimal_track_label.setFixedHeight(15)
        self.minimal_text_layout.addWidget(self.minimal_track_label)
        self.minimal_panel_layout.addWidget(self.minimal_text_box, 1)

        self.minimal_controls_box = QWidget(self.minimal_panel)
        self.minimal_controls_layout = QVBoxLayout(self.minimal_controls_box)
        self.minimal_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.minimal_controls_layout.setSpacing(2)
        self.minimal_header_controls = QHBoxLayout()
        self.minimal_header_controls.setContentsMargins(0, 0, 0, 0)
        self.minimal_header_controls.setSpacing(3)
        self.minimal_header_controls.addStretch(1)
        self.minimal_media_controls = QHBoxLayout()
        self.minimal_media_controls.setContentsMargins(0, 0, 0, 0)
        self.minimal_media_controls.setSpacing(3)
        self.minimal_controls_layout.addLayout(self.minimal_header_controls)
        self.minimal_controls_layout.addLayout(self.minimal_media_controls)
        self.minimal_panel_layout.addWidget(self.minimal_controls_box)
        self.card_layout.insertWidget(0, self.minimal_panel)
        self.minimal_panel.hide()

        apply_technical_font(self.time_label, 24.0, weight=QFont.Weight.Light, stretch=QFont.Stretch.Condensed)
        # One shared secondary size keeps location, Windows time, radio name and
        # track metadata visually consistent without changing the HUD footprint.
        secondary_text_pt = 7.7
        apply_technical_font(self.pc_time_label, secondary_text_pt, weight=QFont.Weight.DemiBold, stretch=QFont.Stretch.Condensed)
        apply_technical_font(self.city_label, secondary_text_pt, weight=QFont.Weight.DemiBold, stretch=QFont.Stretch.Condensed)
        apply_technical_font(self.radio_station_label, secondary_text_pt, weight=QFont.Weight.DemiBold, stretch=QFont.Stretch.SemiCondensed)
        apply_technical_font(self.condition_label, 5.4, weight=QFont.Weight.DemiBold, stretch=QFont.Stretch.SemiCondensed)
        apply_technical_font(self.track_label, secondary_text_pt, weight=QFont.Weight.Normal, stretch=QFont.Stretch.SemiCondensed)
        close_font = QFont(self.close_button.font())
        close_font.setPointSizeF(12.0)
        close_font.setWeight(QFont.Weight.Bold)
        self.close_button.setFont(close_font)
        for button in (self.previous_button, self.play_button, self.next_button):
            media_font = QFont(button.font())
            media_font.setPointSizeF(7.0)
            media_font.setWeight(QFont.Weight.Bold)
            button.setFont(media_font)
        apply_technical_font(self.minimal_time_label, 24.0, weight=QFont.Weight.Light, stretch=QFont.Stretch.Condensed)
        apply_technical_font(self.minimal_pc_time_label, secondary_text_pt, weight=QFont.Weight.DemiBold, stretch=QFont.Stretch.Condensed)
        apply_technical_font(self.minimal_weather_label, secondary_text_pt, weight=QFont.Weight.DemiBold, stretch=QFont.Stretch.Condensed)
        apply_technical_font(self.minimal_track_label, secondary_text_pt, weight=QFont.Weight.Normal, stretch=QFont.Stretch.Condensed)
        for frame in self._hud_clip_frames.values():
            frame.refresh_font_baseline()
        self.apply_hud_layout()

        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(0, 0, 0, 0)
        self.outer_layout.addWidget(self.card, 1)

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(15_000)
        self.clock_timer.timeout.connect(self.refresh_time)
        self.clock_timer.start()

        self.pc_clock_timer = QTimer(self)
        self.pc_clock_timer.setInterval(1_000)
        self.pc_clock_timer.timeout.connect(self._refresh_pc_time)
        self.pc_clock_timer.start()
        self._refresh_pc_time()

        self.card.set_background_opacity(self.settings.value("widget/background_opacity", 100, type=int))
        self._rebuild_station_combo()
        self.refresh_time()
        self._on_station_changed()
        self.set_compact_mode(True)

    def _media_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("mediaButton")
        button.setFixedSize(18, 18)
        button.setToolTip(tooltip)
        return button

    def retranslate_ui(self) -> None:
        self.language = current_language(self.settings)
        self.minimal_pc_time_label.setToolTip(tr(self.settings, "Heure réelle du PC", "Real PC time"))
        self.pc_time_label.setToolTip(tr(self.settings, "Heure réelle du PC", "Real PC time"))
        self.close_button.setToolTip(tr(self.settings, "Fermer toute l'application", "Close the entire application"))
        self.location_capture_button.retranslate_ui()
        self.previous_button.setToolTip(tr(self.settings, "Station précédente · commande multimédia Fn", "Previous station · Fn media command"))
        self.play_button.setToolTip(tr(self.settings, "Lecture / pause · commande multimédia Fn", "Play / pause · Fn media command"))
        self.next_button.setToolTip(tr(self.settings, "Station suivante · commande multimédia Fn", "Next station · Fn media command"))
        self.volume_slider.setToolTip(f"{tr(self.settings, 'Volume', 'Volume')} : {self.volume_slider.value()}%")

    def set_mode_switch(self, checked: bool) -> None:
        blocker = QSignalBlocker(self.mode_switch)
        self.mode_switch.setChecked(checked)
        del blocker

    def set_detected_location(self, name: str, body: str, raw_location: str = "") -> None:
        """Apply one location or travel transition emitted by the read-only Game.log monitor."""
        self._detected_location_name = str(name or "").strip() or None
        self._detected_location_body = str(body or "").strip() or None
        self._detected_location_raw = str(raw_location or "").strip() or None
        self._detected_location_type = self.settings.value(
            "game_log/location_type", "", type=str
        ).strip()
        self._detected_travel_state = self.settings.value(
            "game_log/travel_state", "location", type=str
        ).strip() or "location"
        self._detected_jurisdiction = self.settings.value(
            "game_log/jurisdiction", "", type=str
        ).strip()
        self._detected_monitored_state = self.settings.value(
            "game_log/monitored_state", "unknown", type=str
        ).strip().casefold() or "unknown"
        saved_clock_mode = self.settings.value(
            "game_log/clock_mode", "", type=str
        ).strip().casefold()
        if saved_clock_mode in {"local", "utc"}:
            self._detected_clock_mode = saved_clock_mode
        else:
            resolved = resolve_verse_location(
                self._detected_location_raw or self._detected_location_name or ""
            )
            self._detected_clock_mode = "utc" if location_uses_utc_clock(resolved) else "local"
        self._manual_location_override = False
        self.refresh_time()

    def clear_detected_location(self) -> None:
        self._detected_location_name = None
        self._detected_location_body = None
        self._detected_location_raw = None
        self._detected_location_type = ""
        self._detected_clock_mode = "local"
        self._detected_travel_state = "location"
        self._detected_jurisdiction = ""
        self._detected_monitored_state = "unknown"
        self.refresh_time()

    def activate_manual_location_override(self) -> None:
        """Show the user's explicit choice until a fresh Game.log event arrives."""
        self._manual_location_override = True
        self._detected_location_name = None
        self._detected_location_body = None
        self._detected_location_raw = None
        self._detected_location_type = ""
        self._detected_clock_mode = "local"
        self._detected_travel_state = "location"
        self._detected_jurisdiction = ""
        self._detected_monitored_state = "unknown"

    def _refresh_pc_time(self) -> None:
        """Refresh the real Windows clock independently from VerseTime."""
        pc_time = QTime.currentTime().toString("HH:mm")
        self.pc_time_label.setText(pc_time)
        self.minimal_pc_time_label.setText(pc_time)

    def _fit_primary_time_font(self, text: str) -> None:
        """Keep the dominant clock inside its compact 84 px left-side column."""
        available = max(1, self.time_label.width() - 2)
        for point_size in (24.0, 23.0, 22.0, 21.0, 20.0, 19.0, 18.0):
            font = QFont(self.time_label.font())
            font.setPointSizeF(point_size)
            font.setWeight(QFont.Weight.Light)
            font.setStretch(QFont.Stretch.Condensed)
            self.time_label.setFont(font)
            if self.time_label.fontMetrics().horizontalAdvance(text) <= available:
                break

    def refresh_time(self) -> None:
        self._refresh_pc_time()
        manual_location_id = normalize_location_id(
            str(self.location_combo.currentData() or "new-babbage")
        )
        automatic = self.settings.value(
            "game_log/auto_location_enabled", True, type=bool
        )
        detected_name = self._detected_location_name if automatic else None
        clock_mode = self._detected_clock_mode if detected_name else "local"
        travel_state = self._detected_travel_state if detected_name else "location"
        jurisdiction = self._detected_jurisdiction if detected_name else ""
        monitored_state = self._detected_monitored_state if detected_name else "unknown"
        if detected_name:
            location_id = visual_location_id_for_body(self._detected_location_body or "")
            try:
                data = simulate_weather_for_location(detected_name, location_id)
                source = tr(self.settings, "Game.log (lecture seule) + VerseTime Astro Atlas", "Game.log (read-only) + VerseTime Astro Atlas")
            except ValueError:
                data = simulate_weather(manual_location_id)
                location_id = manual_location_id
                data["location"] = detected_name
                if travel_state == "non_monitored":
                    data["body"] = ""
                elif self._detected_location_body:
                    data["body"] = self._detected_location_body
                source = tr(self.settings, "Game.log (lecture seule) + horloge spatiale", "Game.log (read-only) + space clock")
        elif automatic:
            # Automatic mode must not silently fall back to the configured
            # default city. Until Game.log yields a reliable location, show an
            # explicit empty state instead of mixing both modes.
            location_id = manual_location_id
            data = simulate_weather(location_id)
            data["location"] = tr(self.settings, "No data available", "No data available")
            data["body"] = ""
            data["condition"] = ""
            source = tr(self.settings, "Game.log (lecture seule) · localisation en attente", "Game.log (read-only) · waiting for location")
            clock_mode = "utc"
        else:
            location_id = manual_location_id
            data = simulate_weather(location_id)
            source = tr(self.settings, "Ville par défaut + VerseTime", "Default city + VerseTime")

        display_time = str(data["local_time"])
        clock_reference = tr(self.settings, "Heure locale SC", "SC local time")
        if clock_mode == "utc":
            utc_now = datetime.now(timezone.utc)
            display_time = f"{utc_now.hour:02d}:{utc_now.minute:02d}"
            clock_reference = tr(self.settings, "Heure spatiale", "Space time")

        data["weather_display"] = translate_weather(
            str(data.get("weather", "")),
            daylight=bool(data.get("is_daylight", False)),
            language=self.language,
        )
        raw_location_text = str(data["location"]).upper()
        location_text = translate_location_name(raw_location_text, self.language).upper()
        normalized_type = self._detected_location_type.casefold().replace("_", " ")
        unknown_site = (
            "unknown site" in normalized_type
            or raw_location_text in {"NO DATA", "NO DATA AVAILABLE", "AUCUNE DONNÉE", "AUCUNE DONNÉE DISPONIBLE"}
        )
        if travel_state == "non_monitored" or raw_location_text == "NON MONITORED ZONE":
            # Legacy saved state migration: monitored-space state is never a place.
            location_text = tr(self.settings, "NO DATA AVAILABLE", "NO DATA AVAILABLE")
            unknown_site = True
            clock_mode = "utc"

        atlas_parent = str(
            data.get("atlas_parent_body") or self._detected_location_body or data.get("body", "")
        ).strip()
        atlas_parent_upper = atlas_parent.upper()
        station_code_match = re.fullmatch(
            r"(?:ARC|CRU|HUR|MIC)-L[1-5]|PYR\d+\s+L[1-5]", atlas_parent_upper
        )
        station_scene = (
            "station" in normalized_type
            or "station" in str(data.get("location", "")).casefold()
            or station_code_match is not None
        ) and not unknown_site
        exact_site = bool(detected_name) and not station_scene and not unknown_site and (
            "settlement" in normalized_type
            or "facility" in normalized_type
            or "bunker" in normalized_type
            or "landing zone" in normalized_type
            or "outpost" in normalized_type
            or "processing" in normalized_type
        )
        if station_scene:
            scene_kind = "station"
        elif travel_state in {"space", "non_monitored"}:
            scene_kind = "space"
        elif body_is_moon(str(data.get("body", ""))):
            scene_kind = "moon"
        else:
            scene_kind = "surface"

        if travel_state == "space":
            city_text = tr(self.settings, "DEEP SPACE", "DEEP SPACE")
        else:
            city_text = location_text
        minimal_time = display_time

        condition_text = secondary_display(
            location_name=location_text,
            weather=str(data["weather_display"]),
            travel_state=travel_state,
            jurisdiction=jurisdiction,
            monitored_state=monitored_state,
            unknown_site=unknown_site,
            station=station_scene,
            exact_site=exact_site,
        )
        self.condition_label.setText(condition_text)
        tooltip_location = translate_location_name(str(data["location"]), self.language)
        tooltip_lines = [
            f"{tooltip_location} · {data['body']}",
            f"{tr(self.settings, 'Heure', 'Time')} : {display_time} ({clock_reference})",
        ]
        if exact_site:
            tooltip_lines.append(f"{tr(self.settings, 'Météo décorative', 'Decorative weather')} : {data['weather_display']}")
        if jurisdiction:
            tooltip_lines.append(f"{tr(self.settings, 'Juridiction', 'Jurisdiction')} : {jurisdiction}")
        tooltip_lines.append(f"{tr(self.settings, 'Source', 'Source')} : {source}")
        self.condition_label.setToolTip("\n".join(tooltip_lines))
        self.time_label.setText(display_time)
        self._fit_primary_time_font(display_time)
        self.minimal_time_label.setText(minimal_time)
        self.city_label.setText(city_text)
        if detected_name:
            detail = tr(self.settings, "Lieu détecté automatiquement", "Location detected automatically")
            if travel_state == "map_preview":
                detail = tr(self.settings, "Lieu prévisualisé sur la carte", "Location previewed on the map")
            elif travel_state == "quantum_destination":
                detail = tr(self.settings, "Destination détectée", "Destination detected")
            elif travel_state == "space":
                detail = tr(self.settings, "Zone spatiale détectée", "Space zone detected")
            elif travel_state == "non_monitored":
                detail = tr(self.settings, "Contexte spatial interne", "Internal space context")
            self.city_label.setToolTip(
                f"{detail} : {tooltip_location} · {data['body']}\n"
                f"{tr(self.settings, 'Référence horaire', 'Time reference')} : {clock_reference}\n"
                + tr(self.settings, "Source : Game.log lu en lecture seule", "Source: Game.log read-only")
            )
        else:
            self.city_label.setToolTip(tr(self.settings, "Lieu par défaut choisi dans Réglage", "Default location selected in Settings"))
        station = self.current_station()
        self.minimal_weather_label.setText(station.display_name.upper())
        self.minimal_weather_label.setToolTip(station.tagline)
        self.card.set_scene(
            location_id,
            str(data['phase']),
            str(data['weather']),
            str(data['weather_display']),
            bool(data['is_daylight']),
            bool(data['is_full_daylight']),
            scene_kind,
        )
        self._apply_theme(self.card.theme)

    # Compatibility for older tests and callers.
    refresh_weather = refresh_time

    def _expanded_hud_elements(self) -> dict[str, QWidget]:
        return {
            "controls": self.top_controls_box,
            "location": self.location_text_box,
            "pc_clock": self.pc_time_box,
            "verse_clock": self.time_text_box,
            "radio_info": self.radio_info_box,
            "media": self.media_controls_box,
            "track": self.track_label,
            "guide_left": self.guide_left,
            "guide_right": self.guide_right,
        }

    def _detach_expanded_hud_elements(self) -> None:
        """Place each native HUD group inside an independently cropped viewport."""
        for layout, widget in (
            (self.left_zone_layout, self.top_controls_box),
            (self.left_zone_layout, self.location_text_box),
            (self.left_zone_layout, self.time_text_box),
            (self.radio_layout, self.radio_info_box),
            (self.radio_layout, self.media_controls_box),
            (self.radio_layout, self.track_label),
        ):
            layout.removeWidget(widget)

        for shell in (self.left_zone, self.center_gap, self.radio_box):
            self.hud_row.removeWidget(shell)
            shell.hide()

        self.expanded_panel.setFixedHeight(HUD_CANVAS_HEIGHT)
        specs = {spec.element_id: spec for spec in HUD_ELEMENT_SPECS}
        for element_id, widget in self._expanded_hud_elements().items():
            spec = specs[element_id]
            widget.setFixedSize(spec.width, spec.height)
            frame = HudClipContainer(
                widget, spec.width, spec.height, self.expanded_panel
            )
            frame.setObjectName(f"widgetHudClip_{element_id}")
            self._hud_clip_frames[element_id] = frame
            frame.show()
        self.apply_hud_layout()

    def set_hud_canvas_size(self, width: int, height: int) -> None:
        """Resize the transparent HUD surface to the active screen."""
        width = max(HUD_CANVAS_WIDTH, int(width))
        height = max(HUD_CANVAS_HEIGHT, int(height))
        self._hud_canvas_width = width
        self._hud_canvas_height = height
        self.outer_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)
        for index in range(self.card_layout.count() - 1, -1, -1):
            item = self.card_layout.itemAt(index)
            if item is not None and item.spacerItem() is not None:
                self.card_layout.takeAt(index)
        self.expanded_panel.setFixedSize(width, height)
        self.card.setFixedSize(width, height)
        self.setFixedSize(width, height)
        self.apply_hud_layout()

    def set_hud_layout_preview(self, layout: object | None) -> None:
        if layout is None:
            self._hud_layout_preview = None
            self._hud_crop_preview = None
            self._hud_scale_preview = None
            self._hud_text_alignment_preview = None
        elif isinstance(layout, dict):
            raw_crops = layout.get(HUD_PREVIEW_CROPS_KEY)
            if isinstance(raw_crops, dict):
                crops = normalize_hud_crops(raw_crops)
            else:
                raw_widths = layout.get(HUD_PREVIEW_WIDTHS_KEY)
                crops = (
                    crops_from_visible_widths(raw_widths)
                    if isinstance(raw_widths, dict)
                    else load_hud_crops(self.settings)
                )
            raw_scales = layout.get(HUD_PREVIEW_SCALES_KEY)
            scales = (
                normalize_hud_scales(raw_scales)
                if isinstance(raw_scales, dict)
                else load_hud_scales(self.settings)
            )
            raw_alignments = layout.get(HUD_PREVIEW_TEXT_ALIGNMENTS_KEY)
            text_alignments = (
                normalize_hud_text_alignments(raw_alignments)
                if isinstance(raw_alignments, dict)
                else load_hud_text_alignments(self.settings)
            )
            raw_screen = layout.get(HUD_PREVIEW_SCREEN_SIZE_KEY)
            if isinstance(raw_screen, dict):
                source_width = max(1, int(raw_screen.get("width", self._hud_canvas_width)))
                source_height = max(1, int(raw_screen.get("height", self._hud_canvas_height)))
            else:
                source_width = self._hud_canvas_width
                source_height = self._hud_canvas_height
            raw_positions = {
                key: value
                for key, value in layout.items()
                if key in {spec.element_id for spec in HUD_ELEMENT_SPECS}
            }
            if source_width != self._hud_canvas_width or source_height != self._hud_canvas_height:
                scale_x = self._hud_canvas_width / source_width
                scale_y = self._hud_canvas_height / source_height
                raw_positions = {
                    key: (int(value[0] * scale_x), int(value[1] * scale_y))
                    if isinstance(value, (list, tuple)) and len(value) >= 2
                    else {
                        "x": int(value.get("x", 0) * scale_x),
                        "y": int(value.get("y", 0) * scale_y),
                    }
                    if isinstance(value, dict)
                    else value
                    for key, value in raw_positions.items()
                }
            self._hud_crop_preview = crops
            self._hud_scale_preview = scales
            self._hud_text_alignment_preview = text_alignments
            self._hud_layout_preview = normalize_hud_screen_layout(
                raw_positions,
                crops,
                self._hud_canvas_width,
                self._hud_canvas_height,
                scales,
            )
        else:
            self._hud_layout_preview = None
            self._hud_crop_preview = None
            self._hud_scale_preview = None
            self._hud_text_alignment_preview = None
        self.apply_hud_layout()

    @staticmethod
    def _visible_segment(
        widget: QWidget, crop_left: int, visible_width: int
    ) -> tuple[int, int]:
        viewport_start = int(crop_left)
        viewport_end = viewport_start + int(visible_width)
        widget_start = int(widget.x())
        widget_end = widget_start + int(widget.width())
        visible_start = max(widget_start, viewport_start)
        visible_end = min(widget_end, viewport_end)
        return max(0, visible_start - widget_start), max(1, visible_end - visible_start)

    def _apply_text_crop_widths(
        self,
        crops: dict[str, dict[str, int]],
        scales: dict[str, int],
        text_alignments: dict[str, str],
    ) -> None:
        self.location_text_layout.activate()
        self.pc_time_layout.activate()
        self.time_text_layout.activate()
        self.radio_info_layout.activate()
        widths = hud_visible_widths_from_crops(crops)

        def alignment_flag(element_id: str) -> Qt.AlignmentFlag:
            horizontal = (
                Qt.AlignmentFlag.AlignRight
                if text_alignments[element_id] == "right"
                else Qt.AlignmentFlag.AlignLeft
            )
            return horizontal | Qt.AlignmentFlag.AlignVCenter

        self.city_label.setAlignment(alignment_flag("location"))
        self.pc_time_label.setAlignment(alignment_flag("pc_clock"))
        self.time_label.setAlignment(alignment_flag("verse_clock"))
        self.radio_station_label.setAlignment(alignment_flag("radio_info"))
        self.track_label.setAlignment(alignment_flag("track"))
        self.condition_label.setAlignment(alignment_flag("location"))

        location_scale = scales["location"] / 100.0
        pc_scale = scales["pc_clock"] / 100.0
        verse_scale = scales["verse_clock"] / 100.0
        radio_scale = scales["radio_info"] / 100.0
        track_scale = scales["track"] / 100.0

        location_left = int(round(crops["location"]["left"] * location_scale))
        location_width = max(1, int(round(widths["location"] * location_scale)))
        location_start, location_part = self._visible_segment(
            self.city_label, location_left, location_width
        )
        self.city_label.set_viewport(location_start, location_part)

        pc_left = int(round(crops["pc_clock"]["left"] * pc_scale))
        pc_right = int(round(crops["pc_clock"]["right"] * pc_scale))
        self.pc_time_label.setContentsMargins(pc_left, 0, pc_right, 0)

        verse_left = int(round(crops["verse_clock"]["left"] * verse_scale))
        verse_right = int(round(crops["verse_clock"]["right"] * verse_scale))
        self.time_label.setContentsMargins(verse_left, 0, verse_right, 0)

        radio_left = int(round(crops["radio_info"]["left"] * radio_scale))
        radio_width = max(1, int(round(widths["radio_info"] * radio_scale)))
        radio_start, radio_part = self._visible_segment(
            self.radio_station_label, radio_left, radio_width
        )
        self.radio_station_label.set_viewport(radio_start, radio_part)

        track_left = int(round(crops["track"]["left"] * track_scale))
        track_width = max(1, int(round(widths["track"] * track_scale)))
        self.track_label.set_viewport(track_left, track_width)

    def hud_mask_rects(self) -> list[QRect]:
        rects: list[QRect] = []
        for frame in self._hud_clip_frames.values():
            if frame.isVisible():
                rects.append(frame.geometry().adjusted(-2, -2, 2, 2))
        return rects

    def apply_hud_layout(self) -> None:
        crops = self._hud_crop_preview or load_hud_crops(self.settings)
        scales = self._hud_scale_preview or load_hud_scales(self.settings)
        text_alignments = (
            self._hud_text_alignment_preview
            or load_hud_text_alignments(self.settings)
        )
        layout = self._hud_layout_preview or load_hud_screen_layout(
            self.settings,
            self._hud_canvas_width,
            self._hud_canvas_height,
            crops,
            scales,
        )
        crops = normalize_hud_crops(crops)
        scales = normalize_hud_scales(scales)
        text_alignments = normalize_hud_text_alignments(text_alignments)
        layout = normalize_hud_screen_layout(
            layout,
            crops,
            self._hud_canvas_width,
            self._hud_canvas_height,
            scales,
        )
        for element_id, frame in self._hud_clip_frames.items():
            crop = crops[element_id]
            frame.set_transform(
                crop["left"], crop["right"], scales[element_id]
            )
            x, y = layout[element_id]
            frame.move(x, y)
            frame.raise_()
        self._apply_text_crop_widths(crops, scales, text_alignments)
        self.expanded_panel.update()
        self.hud_region_changed.emit(self.hud_mask_rects())

    def set_detected_vehicle(
        self, manufacturer_id: str, vehicle_code: str = ""
    ) -> None:
        """Retain detected vehicle context without changing the HUD colour."""
        self.card.set_vehicle_context(manufacturer_id, vehicle_code)

    def refresh_theme(self) -> None:
        """Refresh the already-open normal widget immediately."""
        self.card.refresh_theme()
        self._apply_theme(self.card.theme)
        for child in self.findChildren(QWidget):
            style = child.style()
            if style is not None:
                style.unpolish(child)
                style.polish(child)
            child.update()
        self.card.update()
        self.update()

    def _apply_theme(self, theme: SpaceTheme) -> None:
        accent = QColor(theme.accent)
        highlight = QColor(theme.highlight)
        deep = QColor(theme.deep)
        visual = self.card.visual_style

        def css_rgba(color: QColor, opacity: float) -> str:
            alpha = max(0, min(255, round(255 * opacity)))
            return f"rgba({color.red()},{color.green()},{color.blue()},{alpha})"

        accent_css = css_rgba(accent, 0.69)
        accent_opaque = f"rgb({accent.red()},{accent.green()},{accent.blue()})"
        highlight_css = f"rgb({highlight.red()},{highlight.green()},{highlight.blue()})"
        text_css = highlight_css
        border_css = css_rgba(accent, visual.button_border_opacity)
        fill_opacity = visual.button_fill_opacity
        if self._compact and visual.button_style not in {"glass", "industrial"}:
            fill_opacity *= 0.30
        button_fill = css_rgba(deep, fill_opacity)
        close_fill = css_rgba(deep, min(1.0, fill_opacity + 0.06))
        hover_fill = css_rgba(accent, min(0.88, fill_opacity + 0.18))
        radius = visual.button_radius
        weight = 700
        extra_border = ""

        if visual.button_style == "industrial":
            radius = min(radius, 2.0)
            weight = 800
            extra_border = f"border-bottom: 2px solid {css_rgba(highlight, 0.52)};"
        elif visual.button_style == "hud":
            radius = 0.0
            button_fill = "transparent"
            close_fill = "transparent"
            hover_fill = css_rgba(accent, 0.30)
            weight = 700
        elif visual.button_style == "glass":
            radius = max(radius, 8.0)
            button_fill = css_rgba(highlight, max(0.08, fill_opacity * 0.28))
            close_fill = css_rgba(highlight, max(0.09, fill_opacity * 0.30))
            hover_fill = css_rgba(highlight, max(0.18, fill_opacity * 0.48))
            border_css = css_rgba(highlight, max(0.28, visual.button_border_opacity * 0.72))
            weight = 600
        elif visual.button_style == "minimal":
            radius = 0.0
            button_fill = "transparent"
            close_fill = "transparent"
            hover_fill = css_rgba(accent, 0.16)
            border_css = "transparent"
            extra_border = f"border-bottom: 1px solid {css_rgba(accent, 0.62)};"
            weight = 600

        self.mode_switch.set_accent_color(theme.accent)
        self.guide_left.set_theme(accent, highlight)
        self.guide_right.set_theme(accent, highlight)
        self.city_label.set_text_color(highlight)
        self.radio_station_label.set_text_color(QColor("white"))
        self.track_label.set_text_color(highlight)
        self.minimal_track_label.set_text_color(highlight)
        self.setStyleSheet(
            f"""
            QWidget {{ background: transparent; }}
            QLabel#widgetCondition {{ color: white; letter-spacing: 0.45px; }}
            QLabel#widgetCityLabel {{ color: {text_css}; letter-spacing: 0.55px; }}
            QLabel#widgetStationName {{ color: white; letter-spacing: 0.25px; }}
            QLabel#widgetPcTime, QLabel#widgetMinimalPcTime {{ color: white; letter-spacing: 0.35px; }}
            QLabel#widgetMinimalWeather {{ color: {text_css}; letter-spacing: 0.2px; }}
            QLabel#widgetMinimalTrack {{ color: {text_css}; }}
            QLabel#widgetMinimalTime, QLabel#widgetTemperature {{ color: {text_css}; }}
            QPushButton#widgetCloseButton {{
                background: {close_fill}; border: 1px solid {border_css}; border-radius: {radius:.1f}px;
                {extra_border}
                color: {highlight_css}; padding: 0; font-weight: {weight};
            }}
            QPushButton#widgetCloseButton:hover {{ background: rgba(165,48,55,185); }}
            QPushButton#mediaButton {{
                background: {button_fill}; border: 1px solid {border_css}; border-radius: {radius:.1f}px;
                {extra_border}
                color: {highlight_css}; padding: 0; font-weight: {weight};
            }}
            QPushButton#mediaButton:hover {{ background: {hover_fill}; }}
            QSlider#widgetVolume::groove:horizontal {{
                height: 3px; background: rgba(255,255,255,105); border-radius: 1px;
            }}
            QSlider#widgetVolume::sub-page:horizontal {{ background: {accent_css}; border-radius: 1px; }}
            QSlider#widgetVolume::handle:horizontal {{
                width: 10px; margin: -4px 0; background: {highlight_css}; border-radius: 5px;
            }}
            """
        )

    def _rebuild_station_combo(self) -> None:
        saved = self.settings.value("radio/station", DEFAULT_STATION_ID, type=str)
        self._playable = playable_stations(self.settings)
        blocker = QSignalBlocker(self.station_combo)
        self.station_combo.clear()
        for station in self._playable:
            self.station_combo.addItem(station.display_name, station.station_id)
        index = self.station_combo.findData(saved)
        if index < 0:
            index = self.station_combo.findData(DEFAULT_STATION_ID)
        self.station_combo.setCurrentIndex(max(0, index))
        del blocker
        has_multiple = len(self._playable) > 1
        self.previous_button.setEnabled(has_multiple)
        self.next_button.setEnabled(has_multiple)
        self.previous_button.setToolTip(tr(self.settings, "Station précédente · commande multimédia Fn", "Previous station · Fn media command"))
        self.next_button.setToolTip(tr(self.settings, "Station suivante · commande multimédia Fn", "Next station · Fn media command"))

    def current_station(self) -> RadioStation:
        return STATION_BY_ID.get(
            str(self.station_combo.currentData() or DEFAULT_STATION_ID), STATION_BY_ID[DEFAULT_STATION_ID]
        )

    def stream_urls(self, station: RadioStation | None = None) -> tuple[str, ...]:
        return station_streams(self.settings, station or self.current_station())

    # Compatibility for old callers.
    def stream_url(self, station: RadioStation | None = None) -> str:
        urls = self.stream_urls(station)
        return urls[0] if urls else ""

    def change_station(self, delta: int) -> None:
        count = self.station_combo.count()
        if count <= 1:
            self._set_status(tr(self.settings, "Aucune autre station radio disponible.", "No other radio station is available."))
            return
        self.station_combo.setCurrentIndex((self.station_combo.currentIndex() + delta) % count)

    def _set_status(self, text: str) -> None:
        self.card.setToolTip(text)
        self.station_combo.setToolTip(text)

    def _on_station_changed(self) -> None:
        station = self.current_station()
        self.track_label.setText(tr(self.settings, "Connexion aux métadonnées radio…", "Connecting to radio metadata…"))
        self.minimal_track_label.setText(tr(self.settings, "Connexion aux métadonnées radio…", "Connecting to radio metadata…"))
        self.settings.setValue("radio/station", station.station_id)
        self.radio_station_label.setText(station.display_name.upper())
        self.minimal_weather_label.setText(station.display_name.upper())
        self.minimal_weather_label.setToolTip(station.tagline)
        if self.engine.state in {"playing", "connecting"}:
            self.engine.play(self.stream_urls(station))
        else:
            self._set_status(tr(self.settings, f"{station.name} · {station.frequency} prête", f"{station.name} · {station.frequency} ready"))

    def toggle_playback(self) -> None:
        self._set_status(tr(self.settings, "Recherche d'un flux radio actif…", "Searching for an active radio stream…"))
        self.engine.toggle(self.stream_urls())

    def stop_playback(self) -> None:
        self.engine.stop()

    def change_volume(self, value: int) -> None:
        self.engine.set_volume(value)
        self.settings.setValue("radio/volume", value)
        self.volume_slider.setToolTip(f"{tr(self.settings, 'Volume', 'Volume')} : {value}%")

    def _on_audio_state(self, state: str) -> None:
        self.play_button.setText("Ⅱ" if state in {"playing", "connecting"} else "▶")
        status = {
            "connecting": tr(self.settings, "Recherche d'un flux radio actif…", "Searching for an active radio stream…"),
            "playing": tr(self.settings, f"Lecture · {self.current_station().name}", f"Playing · {self.current_station().name}"),
            "paused": tr(self.settings, "En pause", "Paused"),
            "stopped": tr(self.settings, "Lecture arrêtée", "Playback stopped"),
            "error": tr(self.settings, "Flux audio indisponible", "Audio stream unavailable"),
        }.get(state, state)
        self._set_status(status)

    def _on_track_changed(self, artist: str, title: str) -> None:
        artist = " ".join(str(artist or "").split())
        title = " ".join(str(title or "").split())
        if artist and title:
            display = f"{artist.upper()}  —  {title}"
        else:
            display = title or artist or tr(self.settings, "Titre en attente du flux radio", "Waiting for radio track metadata")
        self.track_label.setText(display)
        self.minimal_track_label.setText(display)

    def _on_audio_error(self, message: str) -> None:
        self._set_status(f"{tr(self.settings, 'Audio indisponible', 'Audio unavailable')} : {message}")

    def _on_metadata_status(self, state: str) -> None:
        if state == "connecting":
            text = tr(self.settings, "Connexion aux métadonnées radio…", "Connecting to radio metadata…")
        elif state == "connected":
            text = tr(self.settings, "Métadonnées connectées · titre en attente", "Metadata connected · waiting for track title")
        elif state == "unavailable":
            text = tr(self.settings, "Titre non diffusé par la radio pour le moment", "The radio is not providing a track title right now")
        elif state == "stopped":
            return
        else:
            return
        if not self.engine.has_track_metadata:
            self.track_label.setText(text)
            self.minimal_track_label.setText(text)
        self._set_status(text)

    def apply_external_settings(self) -> None:
        self.retranslate_ui()
        self.settings.remove("game_log/manual_override_pending")
        self._manual_location_override = False
        if not self.settings.value("game_log/auto_location_enabled", True, type=bool):
            self._detected_location_name = None
            self._detected_location_body = None
            self._detected_location_raw = None
            self._detected_location_type = ""
            self._detected_clock_mode = "local"
            self._detected_travel_state = "location"
        self.card.set_background_opacity(
            self.settings.value("widget/background_opacity", 100, type=int)
        )
        hud_primary = normalize_hud_color(
            self.settings.value(HUD_COLOR_SETTINGS_KEY, DEFAULT_HUD_COLOR, type=str)
        )
        saved_secondary = self.settings.value(
            HUD_SECONDARY_COLOR_SETTINGS_KEY, "", type=str
        ).strip()
        hud_secondary = (
            normalize_hud_secondary_color(saved_secondary)
            if saved_secondary
            else hud_theme_colors(hud_primary)[1]
        )
        self.card.set_hud_colors(hud_primary, hud_secondary)
        location_id = self.settings.value("verse_time/location", "new-babbage", type=str)
        location_index = self.location_combo.findData(location_id)
        if location_index >= 0:
            self.location_combo.setCurrentIndex(location_index)
        self._rebuild_station_combo()
        self.engine.set_output_device(self.settings.value("radio/output_device", "", type=str))
        volume = self.settings.value("radio/volume", 35, type=int)
        self.volume_slider.setValue(max(0, min(100, volume)))
        self.refresh_time()
        self.refresh_theme()
        self._on_station_changed()
        self.apply_hud_layout()

    def set_compact_mode(self, enabled: bool) -> None:
        # Compatibility: the normal widget remains the expanded compact design.
        del enabled
        self.set_minimal_mode(False)

    def set_minimal_mode(self, enabled: bool) -> None:
        """Compatibility entry point: Mini mode was removed in 1.1.12."""
        del enabled
        self._set_compact_state(False, with_controls=False)

    def set_lite_mode(self, enabled: bool) -> None:
        """Compatibility entry point: Widget Lite now resolves to the normal HUD."""
        del enabled
        self._set_compact_state(False, with_controls=False)

    def _set_compact_state(self, enabled: bool, with_controls: bool) -> None:
        enabled = bool(enabled)
        with_controls = bool(with_controls and enabled)
        if enabled == self._compact and with_controls == self._lite_mode:
            return
        self._compact = enabled
        self._lite_mode = with_controls
        self.card.set_minimal_mode(enabled)

        for layout, widget in (
            (self.top_layout, self.close_button),
            (self.top_layout, self.location_capture_button),
            (self.top_layout, self.mode_switch),
            (self.minimal_header_controls, self.close_button),
            (self.minimal_header_controls, self.location_capture_button),
            (self.minimal_header_controls, self.mode_switch),
        ):
            layout.removeWidget(widget)
        for button in (self.previous_button, self.play_button, self.next_button):
            self.media_row.removeWidget(button)
            self.minimal_media_controls.removeWidget(button)

        if enabled:
            self.expanded_panel.hide()
            for widget in (
                self.time_label,
                self.pc_time_label,
                self.city_label,
                self.radio_station_label,
                self.track_label,
                self.volume_slider,
            ):
                widget.hide()
            self.minimal_panel.show()
            self.outer_layout.setContentsMargins(2, 2, 2, 2)
            self.card_layout.setContentsMargins(5, 3, 5, 1)
            self.card_layout.setSpacing(0)
            if with_controls:
                for button in (self.previous_button, self.play_button, self.next_button):
                    button.show()
                    self.minimal_media_controls.addWidget(button)
                self.close_button.show()
                self.location_capture_button.show()
                self.mode_switch.show()
                self.minimal_header_controls.addWidget(self.close_button)
                self.minimal_header_controls.addWidget(self.location_capture_button)
                self.minimal_header_controls.addWidget(self.mode_switch)
                self.minimal_controls_box.show()
            else:
                self.minimal_controls_box.hide()
                self.close_button.hide()
                self.location_capture_button.hide()
                self.mode_switch.hide()
                for button in (self.previous_button, self.play_button, self.next_button):
                    button.hide()
        else:
            self.minimal_panel.hide()
            self.expanded_panel.show()
            self.close_button.show()
            self.location_capture_button.show()
            self.mode_switch.show()
            self.top_layout.addWidget(self.close_button)
            self.top_layout.addWidget(self.location_capture_button)
            self.top_layout.addWidget(self.mode_switch)
            for button in (self.previous_button, self.play_button, self.next_button):
                button.show()
                self.media_row.addWidget(button)
            for widget in (
                self.time_label,
                self.pc_time_label,
                self.city_label,
                self.radio_station_label,
                self.track_label,
                self.volume_slider,
            ):
                widget.show()
            self.outer_layout.setContentsMargins(0, 0, 0, 0)
            self.card_layout.setContentsMargins(0, 1, 0, 0)
            self.card_layout.setSpacing(0)
            self.top_layout.setSpacing(1)

        self.card.setMaximumWidth(16777215)
        self.card.setMaximumHeight(16777215)
        self._update_mini_metrics()
        self._apply_theme(self.card.theme)
        if not enabled:
            self.apply_hud_layout()
        self.updateGeometry()

    def _update_mini_metrics(self) -> None:
        very_small = self.width() <= 285
        if self._compact:
            self.mode_switch.setFixedSize(34, 19)
            if self._lite_mode:
                self.minimal_controls_box.setFixedWidth(100)
                self.minimal_weather_label.setMaximumWidth(136 if very_small else 170)
                self.minimal_track_label.setMaximumWidth(136 if very_small else 170)
            else:
                self.minimal_controls_box.setMinimumWidth(0)
                self.minimal_controls_box.setMaximumWidth(0)
                self.minimal_weather_label.setMaximumWidth(230)
                self.minimal_track_label.setMaximumWidth(230)
            for button in (self.previous_button, self.play_button, self.next_button):
                button.setFixedSize(23, 23)
        else:
            self.close_button.setFixedSize(18, 18)
            self.location_capture_button.setFixedSize(18, 18)
            self.mode_switch.setFixedSize(28, 16)
            self.minimal_controls_box.setMinimumWidth(0)
            self.minimal_controls_box.setMaximumWidth(16777215)
            self.left_zone.setFixedWidth(204)
            self.radio_box.setFixedWidth(204)
            self.location_text_box.setMinimumWidth(0)
            self.location_text_box.setFixedSize(52, 15)
            self.pc_time_box.setMinimumWidth(0)
            self.pc_time_box.setFixedSize(52, 12)
            self.time_text_box.setFixedWidth(84)
            self.time_label.setMinimumWidth(84)
            self.time_label.setMaximumWidth(84)
            self.city_label.setMaximumWidth(52)
            self.condition_label.setMaximumWidth(52)
            self.radio_station_label.setMinimumWidth(0)
            self.radio_station_label.setMaximumWidth(99)
            for button in (self.previous_button, self.play_button, self.next_button):
                button.setFixedSize(18, 18)
        self.volume_slider.setMinimumWidth(46 if not self._compact else 48)
        self.volume_slider.setMaximumWidth(46 if not self._compact else (80 if very_small else 110))

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._update_mini_metrics()
        if not self._compact:
            self.apply_hud_layout()
        super().resizeEvent(event)

    def shutdown(self) -> None:
        self.engine.shutdown()
