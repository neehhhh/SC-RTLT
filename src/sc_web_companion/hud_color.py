from __future__ import annotations

import re

DEFAULT_HUD_COLOR = "#46C9F2"
DEFAULT_HUD_SECONDARY_COLOR = "#94E0F7"
HUD_COLOR_SETTINGS_KEY = "widget/hud_color"
HUD_SECONDARY_COLOR_SETTINGS_KEY = "widget/hud_secondary_color"
_HEX_COLOR = re.compile(r"^#?([0-9a-fA-F]{6})$")
_SHORT_HEX_COLOR = re.compile(r"^#?([0-9a-fA-F]{3})$")


def normalize_hud_color(value: object, default: str = DEFAULT_HUD_COLOR) -> str:
    """Return a stable opaque #RRGGBB colour for the HUD."""
    text = str(value or "").strip()
    match = _HEX_COLOR.fullmatch(text)
    if match:
        return f"#{match.group(1).upper()}"
    short = _SHORT_HEX_COLOR.fullmatch(text)
    if short:
        digits = short.group(1).upper()
        return "#" + "".join(character * 2 for character in digits)
    fallback = str(default or DEFAULT_HUD_COLOR).strip()
    match = _HEX_COLOR.fullmatch(fallback)
    if match:
        return f"#{match.group(1).upper()}"
    short = _SHORT_HEX_COLOR.fullmatch(fallback)
    if short:
        digits = short.group(1).upper()
        return "#" + "".join(character * 2 for character in digits)
    return DEFAULT_HUD_COLOR


def normalize_hud_secondary_color(value: object) -> str:
    return normalize_hud_color(value, DEFAULT_HUD_SECONDARY_COLOR)


def _rgb(value: str) -> tuple[int, int, int]:
    normalized = normalize_hud_color(value)
    return tuple(int(normalized[index:index + 2], 16) for index in (1, 3, 5))


def _blend(first: tuple[int, int, int], second: tuple[int, int, int], second_ratio: float) -> tuple[int, int, int]:
    ratio = max(0.0, min(1.0, float(second_ratio)))
    inverse = 1.0 - ratio
    return tuple(round(a * inverse + b * ratio) for a, b in zip(first, second))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


def hud_theme_colors(
    primary: object,
    secondary: object | None = None,
) -> tuple[str, str, str]:
    """Return primary accent, secondary highlight and a shared deep tone.

    Calls that only provide the primary colour retain the legacy behaviour by
    deriving a pale highlight automatically. New callers can provide a manual
    secondary colour.
    """
    accent = normalize_hud_color(primary)
    accent_rgb = _rgb(accent)
    if secondary is None:
        highlight_rgb = _blend(accent_rgb, (255, 255, 255), 0.42)
        highlight = _hex(highlight_rgb)
        deep_rgb = _blend(accent_rgb, (0, 0, 0), 0.72)
    else:
        highlight = normalize_hud_secondary_color(secondary)
        # The deep shade remains tied to the primary colour so existing HUD
        # contrast is preserved when a secondary highlight is introduced.
        deep_rgb = _blend(accent_rgb, (0, 0, 0), 0.72)
    return accent, highlight, _hex(deep_rgb)
