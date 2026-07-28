from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtGui import QColor

from .config import config_directory


_ALLOWED_EFFECTS = {"ice", "industrial", "city", "gas", "desert", "heat", "mist", "orbit"}
_ALLOWED_FRAME_STYLES = {"rounded", "industrial", "hud", "glass", "minimal"}
_ALLOWED_BUTTON_STYLES = {"rounded", "industrial", "hud", "glass", "minimal"}
_MAX_STYLE_BYTES = 512 * 1024
_MAX_QSS_CHARS = 120_000
_FORBIDDEN_QSS_TOKENS = ("@import", "url(")


@dataclass(frozen=True, slots=True)
class ThemePalette:
    accent: str
    highlight: str
    deep: str
    effect: str = "orbit"
    planet_x: float = 0.82
    planet_y: float = 1.03
    planet_radius: float = 0.64


@dataclass(frozen=True, slots=True)
class WidgetVisualTheme:
    """Safe visual treatment applied above the location-specific palette."""

    frame_style: str = "rounded"
    button_style: str = "rounded"
    corner_radius: float = 20.0
    border_width: float = 1.0
    panel_opacity: float = 1.0
    planet_intensity: float = 1.0
    orbit_intensity: float = 1.0
    effect_intensity: float = 1.0
    weather_intensity: float = 1.0
    star_density: float = 1.0
    grid_opacity: float = 0.0
    scanline_opacity: float = 0.0
    glass_highlight: float = 0.0
    corner_marks: bool = False
    inner_border: bool = True
    button_fill_opacity: float = 0.76
    button_border_opacity: float = 0.70
    button_radius: float = 7.0


DEFAULT_WIDGET_VISUAL = WidgetVisualTheme()


@dataclass(frozen=True, slots=True)
class LoadedTheme:
    name: str
    app_qss: str
    default_palette: ThemePalette | None
    location_palettes: dict[str, ThemePalette]
    widget_visual: WidgetVisualTheme = DEFAULT_WIDGET_VISUAL
    source_path: Path | None = None


DEFAULT_LOADED_THEME = LoadedTheme(
    "Thème d’origine",
    "",
    None,
    {},
    DEFAULT_WIDGET_VISUAL,
    None,
)


def installed_theme_path(suffix: str = ".style") -> Path:
    directory = config_directory() / "themes"
    directory.mkdir(parents=True, exist_ok=True)
    normalized = ".qss" if str(suffix).casefold() == ".qss" else ".style"
    return directory / f"active{normalized}"


def _safe_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _safe_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "oui", "on"}:
        return True
    if text in {"0", "false", "no", "non", "off"}:
        return False
    return default


def _safe_choice(value: Any, default: str, allowed: set[str], field_name: str) -> str:
    text = str(value if value is not None else default).strip().casefold()
    if text not in allowed:
        raise ValueError(f"Valeur inconnue pour {field_name}: {text}")
    return text


def _safe_color(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    color = QColor(text)
    if not color.isValid() or color.alpha() != 255:
        raise ValueError(f"Couleur invalide pour {field_name}")
    return color.name(QColor.NameFormat.HexRgb)


def _safe_qss(value: Any) -> str:
    text = str(value or "")
    if len(text) > _MAX_QSS_CHARS:
        raise ValueError("La feuille de style du thème est trop volumineuse")
    lowered = text.casefold().replace(" ", "")
    if "\x00" in text or any(token in lowered for token in _FORBIDDEN_QSS_TOKENS):
        raise ValueError("Les imports et URL externes sont interdits dans les thèmes")
    return text


def _palette(payload: Any, *, section: str) -> ThemePalette:
    if not isinstance(payload, dict):
        raise ValueError(f"La section {section} doit être un objet JSON")
    effect = _safe_choice(payload.get("effect"), "orbit", _ALLOWED_EFFECTS, f"{section}.effect")
    return ThemePalette(
        accent=_safe_color(payload.get("accent"), f"{section}.accent"),
        highlight=_safe_color(payload.get("highlight"), f"{section}.highlight"),
        deep=_safe_color(payload.get("deep"), f"{section}.deep"),
        effect=effect,
        planet_x=_safe_float(payload.get("planet_x", 0.82), 0.82, 0.30, 1.30),
        planet_y=_safe_float(payload.get("planet_y", 1.03), 1.03, 0.30, 1.45),
        planet_radius=_safe_float(payload.get("planet_radius", 0.64), 0.64, 0.25, 1.10),
    )


def _widget_visual(payload: Any) -> WidgetVisualTheme:
    if payload is None:
        return DEFAULT_WIDGET_VISUAL
    if not isinstance(payload, dict):
        raise ValueError("widget.visual doit être un objet JSON")
    return WidgetVisualTheme(
        frame_style=_safe_choice(
            payload.get("frame_style"),
            DEFAULT_WIDGET_VISUAL.frame_style,
            _ALLOWED_FRAME_STYLES,
            "widget.visual.frame_style",
        ),
        button_style=_safe_choice(
            payload.get("button_style"),
            DEFAULT_WIDGET_VISUAL.button_style,
            _ALLOWED_BUTTON_STYLES,
            "widget.visual.button_style",
        ),
        corner_radius=_safe_float(payload.get("corner_radius"), 20.0, 0.0, 28.0),
        border_width=_safe_float(payload.get("border_width"), 1.0, 0.4, 3.0),
        panel_opacity=_safe_float(payload.get("panel_opacity"), 1.0, 0.05, 1.0),
        planet_intensity=_safe_float(payload.get("planet_intensity"), 1.0, 0.0, 1.0),
        orbit_intensity=_safe_float(payload.get("orbit_intensity"), 1.0, 0.0, 1.0),
        effect_intensity=_safe_float(payload.get("effect_intensity"), 1.0, 0.0, 1.0),
        weather_intensity=_safe_float(payload.get("weather_intensity"), 1.0, 0.0, 1.0),
        star_density=_safe_float(payload.get("star_density"), 1.0, 0.0, 1.0),
        grid_opacity=_safe_float(payload.get("grid_opacity"), 0.0, 0.0, 0.45),
        scanline_opacity=_safe_float(payload.get("scanline_opacity"), 0.0, 0.0, 0.25),
        glass_highlight=_safe_float(payload.get("glass_highlight"), 0.0, 0.0, 0.45),
        corner_marks=_safe_bool(payload.get("corner_marks"), False),
        inner_border=_safe_bool(payload.get("inner_border"), True),
        button_fill_opacity=_safe_float(payload.get("button_fill_opacity"), 0.76, 0.0, 1.0),
        button_border_opacity=_safe_float(payload.get("button_border_opacity"), 0.70, 0.0, 1.0),
        button_radius=_safe_float(payload.get("button_radius"), 7.0, 0.0, 12.0),
    )


def load_theme_file(path: str | Path | None) -> LoadedTheme:
    if not path:
        return DEFAULT_LOADED_THEME
    source = Path(path).expanduser()
    if not source.is_file():
        raise ValueError("Le fichier de thème est introuvable")
    if source.stat().st_size > _MAX_STYLE_BYTES:
        raise ValueError("Le fichier de thème est trop volumineux")

    if source.suffix.casefold() == ".qss":
        qss = _safe_qss(source.read_text(encoding="utf-8"))
        return LoadedTheme(source.stem, qss, None, {}, DEFAULT_WIDGET_VISUAL, source)

    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Fichier .style invalide : {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Le thème doit contenir un objet JSON")
    if str(payload.get("format", "")).strip() != "sc-web-companion-style":
        raise ValueError("Format de thème non reconnu")

    try:
        version = int(payload.get("version", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Version de thème non prise en charge") from exc
    if version not in {1, 2}:
        raise ValueError("Version de thème non prise en charge")

    name = str(payload.get("name", source.stem)).strip()[:80] or source.stem
    app_qss = _safe_qss(payload.get("app_qss", ""))

    widget = payload.get("widget", {})
    if not isinstance(widget, dict):
        raise ValueError("La section widget doit être un objet JSON")

    if version == 2:
        # Version 2 deliberately preserves all location colours. It changes only
        # the visual treatment painted above those palettes.
        if widget.get("default") is not None or widget.get("locations") not in (None, {}):
            raise ValueError(
                "Un thème version 2 conserve les couleurs de localisation : "
                "utilise widget.visual, sans widget.default ni widget.locations"
            )
        visual = _widget_visual(widget.get("visual", {}))
        return LoadedTheme(name, app_qss, None, {}, visual, source)

    # Backward-compatible version 1 palette themes.
    default_palette = None
    if widget.get("default") is not None:
        default_palette = _palette(widget["default"], section="widget.default")

    location_palettes: dict[str, ThemePalette] = {}
    locations = widget.get("locations", {})
    if not isinstance(locations, dict):
        raise ValueError("widget.locations doit être un objet JSON")
    for raw_key, raw_palette in locations.items():
        key = str(raw_key or "").strip().casefold().replace("_", "-")
        if not key or len(key) > 80:
            continue
        location_palettes[key] = _palette(raw_palette, section=f"widget.locations.{key}")

    return LoadedTheme(
        name,
        app_qss,
        default_palette,
        location_palettes,
        DEFAULT_WIDGET_VISUAL,
        source,
    )


def install_theme_file(source_path: str | Path) -> LoadedTheme:
    source = Path(source_path).expanduser()
    load_theme_file(source)
    destination = installed_theme_path(source.suffix)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, temporary)
    temporary.replace(destination)
    for suffix in (".style", ".qss"):
        other = installed_theme_path(suffix)
        if other != destination:
            try:
                other.unlink()
            except FileNotFoundError:
                pass
    return load_theme_file(destination)


def remove_installed_theme() -> None:
    for suffix in (".style", ".qss"):
        try:
            installed_theme_path(suffix).unlink()
        except FileNotFoundError:
            pass
