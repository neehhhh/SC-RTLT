from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

# Bahnschrift ships with Windows 10 and Windows 11. No font file is bundled:
# Windows provides the variable family and Qt selects the requested weight/stretch.
WINDOWS_TECH_FAMILY = "Bahnschrift"
FALLBACK_FAMILIES: tuple[str, ...] = ("Arial Narrow", "Segoe UI")


def resolve_ui_family() -> str:
    families = {name.casefold(): name for name in QFontDatabase.families()}
    for candidate in (WINDOWS_TECH_FAMILY, *FALLBACK_FAMILIES):
        match = families.get(candidate.casefold())
        if match:
            return match
    return QApplication.font().family()


def make_font(
    point_size: float,
    *,
    weight: QFont.Weight = QFont.Weight.Normal,
    stretch: QFont.Stretch = QFont.Stretch.Unstretched,
) -> QFont:
    font = QFont(resolve_ui_family())
    font.setPointSizeF(float(point_size))
    font.setWeight(weight)
    font.setStretch(stretch)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def apply_application_typography(app: QApplication) -> str:
    family = resolve_ui_family()
    font = QFont(family)
    font.setPointSizeF(10.0)
    font.setWeight(QFont.Weight.Normal)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setProperty("scwc_font_family", family)
    return family


def apply_technical_font(
    widget: QWidget,
    point_size: float,
    *,
    weight: QFont.Weight = QFont.Weight.Normal,
    stretch: QFont.Stretch = QFont.Stretch.Unstretched,
) -> None:
    widget.setFont(make_font(point_size, weight=weight, stretch=stretch))
