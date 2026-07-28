from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Mapping, Sequence

from PySide6.QtCore import QSettings

# Legacy strip dimensions are kept for migration and compatibility tests.
HUD_CANVAS_WIDTH = 548
HUD_CANVAS_HEIGHT = 65
HUD_SETTINGS_KEY = "widget/hud_layout_v1"
HUD_WIDTHS_SETTINGS_KEY = "widget/hud_visible_widths_v1"
HUD_SCREEN_LAYOUT_KEY = "widget/hud_screen_layout_v2"
HUD_CROPS_SETTINGS_KEY = "widget/hud_crops_v2"
HUD_GROUPS_SETTINGS_KEY = "widget/hud_groups_v1"
HUD_SCALES_SETTINGS_KEY = "widget/hud_scales_v1"
HUD_TEXT_ALIGNMENTS_SETTINGS_KEY = "widget/hud_text_alignments_v1"
HUD_PREVIEW_WIDTHS_KEY = "__visible_widths__"
HUD_PREVIEW_CROPS_KEY = "__crops__"
HUD_PREVIEW_GROUPS_KEY = "__groups__"
HUD_PREVIEW_SCALES_KEY = "__scales__"
HUD_PREVIEW_TEXT_ALIGNMENTS_KEY = "__text_alignments__"
HUD_PREVIEW_SCREEN_SIZE_KEY = "__screen_size__"
HUD_MIN_SCALE_PERCENT = 50
HUD_MAX_SCALE_PERCENT = 200
HUD_TEXT_ELEMENT_IDS = frozenset({"location", "pc_clock", "verse_clock", "radio_info", "track"})
HUD_TEXT_ALIGNMENT_VALUES = frozenset({"left", "right"})

# The user's validated 1.1.17 layout becomes the factory layout. Qt reports
# logical pixels, so a 1920 × 1080 display at 125% scaling is 1536 × 864.
HUD_DEFAULT_REFERENCE_WIDTH = 1536
HUD_DEFAULT_REFERENCE_HEIGHT = 864


@dataclass(frozen=True, slots=True)
class HudElementSpec:
    element_id: str
    label_fr: str
    label_en: str
    width: int
    height: int
    default_x: int
    default_y: int
    minimum_width: int


HUD_ELEMENT_SPECS: tuple[HudElementSpec, ...] = (
    HudElementSpec("controls", "Commandes", "Controls", 66, 18, 0, 25, 18),
    HudElementSpec("location", "Nom du lieu", "Location name", 52, 15, 43, 22, 22),
    HudElementSpec("pc_clock", "Heure du PC", "PC time", 52, 12, 43, 39, 22),
    HudElementSpec("verse_clock", "Heure du lieu", "Location time", 84, 31, 100, 25, 28),
    HudElementSpec("radio_info", "Radio + volume", "Radio + volume", 147, 18, 334, 22, 34),
    HudElementSpec("media", "Commandes radio", "Radio controls", 56, 18, 488, 21, 18),
    HudElementSpec("track", "Artiste + titre", "Artist + title", 204, 15, 337, 42, 36),
    HudElementSpec("guide_left", "Ligne bleue gauche", "Left blue line", 204, 16, 0, 49, 40),
    HudElementSpec("guide_right", "Ligne bleue droite", "Right blue line", 204, 16, 344, 49, 40),
)
HUD_SPEC_BY_ID = {spec.element_id: spec for spec in HUD_ELEMENT_SPECS}

_DEFAULT_HUD_CROPS: dict[str, dict[str, int]] = {
    "controls": {"left": 0, "right": 0},
    "location": {"left": 0, "right": 0},
    "pc_clock": {"left": 0, "right": 0},
    "verse_clock": {"left": 0, "right": 0},
    "radio_info": {"left": 0, "right": 0},
    "media": {"left": 0, "right": 0},
    "track": {"left": 52, "right": 0},
    "guide_left": {"left": 0, "right": 0},
    "guide_right": {"left": 0, "right": 0},
}

_DEFAULT_HUD_SCALES: dict[str, int] = {
    "controls": 111,
    "location": 113,
    "pc_clock": 113,
    "verse_clock": 119,
    "radio_info": 100,
    "media": 100,
    "track": 108,
    "guide_left": 100,
    "guide_right": 100,
}

_DEFAULT_HUD_TEXT_ALIGNMENTS: dict[str, str] = {
    "location": "right",
    "pc_clock": "right",
    "verse_clock": "left",
    "radio_info": "right",
    "track": "right",
}

_DEFAULT_HUD_REFERENCE_LAYOUT: dict[str, tuple[int, int]] = {
    "controls": (407, 38),
    "location": (486, 37),
    "pc_clock": (486, 55),
    "verse_clock": (548, 39),
    "radio_info": (924, 40),
    "media": (1081, 38),
    "track": (939, 55),
    "guide_left": (414, 69),
    "guide_right": (919, 66),
}


def default_hud_scales() -> dict[str, int]:
    return dict(_DEFAULT_HUD_SCALES)


def default_hud_text_alignments() -> dict[str, str]:
    return dict(_DEFAULT_HUD_TEXT_ALIGNMENTS)


def normalize_hud_text_alignments(
    raw: Mapping[str, object] | None,
) -> dict[str, str]:
    normalized = default_hud_text_alignments()
    if not raw:
        return normalized
    for element_id in HUD_TEXT_ELEMENT_IDS:
        value = str(raw.get(element_id, "")).strip().casefold()
        if value in HUD_TEXT_ALIGNMENT_VALUES:
            normalized[element_id] = value
    return normalized


def normalize_hud_scales(raw: Mapping[str, object] | None) -> dict[str, int]:
    normalized = default_hud_scales()
    if not raw:
        return normalized
    for spec in HUD_ELEMENT_SPECS:
        value = raw.get(spec.element_id)
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        normalized[spec.element_id] = max(
            HUD_MIN_SCALE_PERCENT, min(HUD_MAX_SCALE_PERCENT, percent)
        )
    # 1.1.17 stored the PC clock inside the location block. Preserve its
    # previous visual scale when opening that configuration in 1.2.
    if "pc_clock" not in raw and "location" in raw:
        normalized["pc_clock"] = normalized["location"]
    return normalized


def scaled_hud_dimensions(
    spec: HudElementSpec,
    visible_width: int,
    scale_percent: int,
) -> tuple[int, int]:
    scale = max(HUD_MIN_SCALE_PERCENT, min(HUD_MAX_SCALE_PERCENT, int(scale_percent))) / 100.0
    return (
        max(1, int(round(max(1, int(visible_width)) * scale))),
        max(1, int(round(spec.height * scale))),
    )


def default_hud_visible_widths() -> dict[str, int]:
    return {
        spec.element_id: spec.width
        - _DEFAULT_HUD_CROPS[spec.element_id]["left"]
        - _DEFAULT_HUD_CROPS[spec.element_id]["right"]
        for spec in HUD_ELEMENT_SPECS
    }


def normalize_hud_visible_widths(raw: Mapping[str, object] | None) -> dict[str, int]:
    normalized = default_hud_visible_widths()
    if not raw:
        return normalized
    for spec in HUD_ELEMENT_SPECS:
        value = raw.get(spec.element_id)
        try:
            width = int(value)
        except (TypeError, ValueError):
            continue
        normalized[spec.element_id] = max(spec.minimum_width, min(spec.width, width))
    if "pc_clock" not in raw and "location" in raw:
        normalized["pc_clock"] = normalized["location"]
    return normalized


def default_hud_crops() -> dict[str, dict[str, int]]:
    return {key: dict(value) for key, value in _DEFAULT_HUD_CROPS.items()}


def _normalized_crop(spec: HudElementSpec, left: object, right: object) -> dict[str, int]:
    try:
        crop_left = max(0, int(left))
    except (TypeError, ValueError):
        crop_left = 0
    try:
        crop_right = max(0, int(right))
    except (TypeError, ValueError):
        crop_right = 0
    maximum_total = max(0, spec.width - spec.minimum_width)
    crop_left = min(crop_left, maximum_total)
    crop_right = min(crop_right, maximum_total - crop_left)
    return {"left": crop_left, "right": crop_right}


def crops_from_visible_widths(widths: Mapping[str, object] | None) -> dict[str, dict[str, int]]:
    normalized_widths = normalize_hud_visible_widths(widths)
    return {
        spec.element_id: {
            "left": 0,
            "right": spec.width - normalized_widths[spec.element_id],
        }
        for spec in HUD_ELEMENT_SPECS
    }


def normalize_hud_crops(raw: Mapping[str, object] | None) -> dict[str, dict[str, int]]:
    normalized = default_hud_crops()
    if not raw:
        return normalized
    for spec in HUD_ELEMENT_SPECS:
        value = raw.get(spec.element_id)
        if isinstance(value, Mapping):
            normalized[spec.element_id] = _normalized_crop(
                spec, value.get("left", 0), value.get("right", 0)
            )
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            normalized[spec.element_id] = _normalized_crop(spec, value[0], value[1])
        else:
            # A numeric legacy value is interpreted as a visible width.
            try:
                visible = int(value)
            except (TypeError, ValueError):
                continue
            normalized[spec.element_id] = _normalized_crop(
                spec, 0, spec.width - visible
            )
    if "pc_clock" not in raw and "location" in raw:
        normalized["pc_clock"] = dict(normalized["location"])
    return normalized


def hud_visible_widths_from_crops(
    crops: Mapping[str, object] | None,
) -> dict[str, int]:
    normalized = normalize_hud_crops(crops)
    return {
        spec.element_id: max(
            spec.minimum_width,
            spec.width
            - normalized[spec.element_id]["left"]
            - normalized[spec.element_id]["right"],
        )
        for spec in HUD_ELEMENT_SPECS
    }


def default_hud_layout() -> dict[str, tuple[int, int]]:
    return {
        spec.element_id: (spec.default_x, spec.default_y)
        for spec in HUD_ELEMENT_SPECS
    }


def _bounded_position(
    spec: HudElementSpec,
    x: object,
    y: object,
    visible_width: int | None = None,
    scale_percent: int = 100,
    *,
    canvas_width: int = HUD_CANVAS_WIDTH,
    canvas_height: int = HUD_CANVAS_HEIGHT,
) -> tuple[int, int]:
    try:
        pos_x = int(x)
    except (TypeError, ValueError):
        pos_x = spec.default_x
    try:
        pos_y = int(y)
    except (TypeError, ValueError):
        pos_y = spec.default_y
    native_width = spec.width if visible_width is None else max(
        spec.minimum_width, min(spec.width, int(visible_width))
    )
    width, height = scaled_hud_dimensions(spec, native_width, scale_percent)
    return (
        max(0, min(max(0, int(canvas_width) - width), pos_x)),
        max(0, min(max(0, int(canvas_height) - height), pos_y)),
    )


def normalize_hud_layout(
    raw: Mapping[str, object] | None,
    visible_widths: Mapping[str, object] | None = None,
    scales: Mapping[str, object] | None = None,
) -> dict[str, tuple[int, int]]:
    widths = normalize_hud_visible_widths(visible_widths)
    normalized_scales = normalize_hud_scales(scales)
    normalized = default_hud_layout()
    if not raw:
        return normalized
    for spec in HUD_ELEMENT_SPECS:
        value = raw.get(spec.element_id)
        if isinstance(value, Mapping):
            normalized[spec.element_id] = _bounded_position(
                spec,
                value.get("x"),
                value.get("y"),
                widths[spec.element_id],
                normalized_scales[spec.element_id],
            )
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            normalized[spec.element_id] = _bounded_position(
                spec, value[0], value[1], widths[spec.element_id], normalized_scales[spec.element_id]
            )
    return normalized


def default_hud_screen_layout(
    screen_width: int, screen_height: int
) -> dict[str, tuple[int, int]]:
    screen_width = max(1, int(screen_width))
    screen_height = max(1, int(screen_height))
    scale_x = screen_width / HUD_DEFAULT_REFERENCE_WIDTH
    scale_y = screen_height / HUD_DEFAULT_REFERENCE_HEIGHT
    widths = hud_visible_widths_from_crops(default_hud_crops())
    scales = default_hud_scales()
    return {
        spec.element_id: _bounded_position(
            spec,
            round(_DEFAULT_HUD_REFERENCE_LAYOUT[spec.element_id][0] * scale_x),
            round(_DEFAULT_HUD_REFERENCE_LAYOUT[spec.element_id][1] * scale_y),
            widths[spec.element_id],
            scales[spec.element_id],
            canvas_width=screen_width,
            canvas_height=screen_height,
        )
        for spec in HUD_ELEMENT_SPECS
    }


def normalize_hud_screen_layout(
    raw: Mapping[str, object] | None,
    crops: Mapping[str, object] | None,
    screen_width: int,
    screen_height: int,
    scales: Mapping[str, object] | None = None,
) -> dict[str, tuple[int, int]]:
    screen_width = max(1, int(screen_width))
    screen_height = max(1, int(screen_height))
    normalized_crops = normalize_hud_crops(crops)
    widths = hud_visible_widths_from_crops(normalized_crops)
    normalized_scales = normalize_hud_scales(scales)
    normalized = default_hud_screen_layout(screen_width, screen_height)
    if not raw:
        return normalized
    for spec in HUD_ELEMENT_SPECS:
        value = raw.get(spec.element_id)
        if isinstance(value, Mapping):
            normalized[spec.element_id] = _bounded_position(
                spec,
                value.get("x"),
                value.get("y"),
                widths[spec.element_id],
                normalized_scales[spec.element_id],
                canvas_width=screen_width,
                canvas_height=screen_height,
            )
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            normalized[spec.element_id] = _bounded_position(
                spec,
                value[0],
                value[1],
                widths[spec.element_id],
                normalized_scales[spec.element_id],
                canvas_width=screen_width,
                canvas_height=screen_height,
            )
    return normalized


def load_hud_visible_widths(settings: QSettings) -> dict[str, int]:
    payload = settings.value(HUD_WIDTHS_SETTINGS_KEY, "", type=str).strip()
    if not payload:
        return default_hud_visible_widths()
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default_hud_visible_widths()
    return normalize_hud_visible_widths(raw if isinstance(raw, dict) else None)


def save_hud_visible_widths(
    settings: QSettings, widths: Mapping[str, object] | None
) -> dict[str, int]:
    normalized = normalize_hud_visible_widths(widths)
    settings.setValue(
        HUD_WIDTHS_SETTINGS_KEY,
        json.dumps(normalized, separators=(",", ":")),
    )
    settings.sync()
    return normalized


def load_hud_crops(settings: QSettings) -> dict[str, dict[str, int]]:
    payload = settings.value(HUD_CROPS_SETTINGS_KEY, "", type=str).strip()
    if payload:
        try:
            raw = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            return normalize_hud_crops(raw)
    legacy_widths_payload = settings.value(HUD_WIDTHS_SETTINGS_KEY, "", type=str).strip()
    if legacy_widths_payload:
        return crops_from_visible_widths(load_hud_visible_widths(settings))
    has_existing_layout = bool(
        settings.value(HUD_SCREEN_LAYOUT_KEY, "", type=str).strip()
        or settings.value(HUD_SETTINGS_KEY, "", type=str).strip()
    )
    if has_existing_layout:
        return {spec.element_id: {"left": 0, "right": 0} for spec in HUD_ELEMENT_SPECS}
    return default_hud_crops()


def save_hud_crops(
    settings: QSettings, crops: Mapping[str, object] | None
) -> dict[str, dict[str, int]]:
    normalized = normalize_hud_crops(crops)
    settings.setValue(
        HUD_CROPS_SETTINGS_KEY,
        json.dumps(normalized, separators=(",", ":")),
    )
    # Keep the v1 visible-width key current so older integrations still work.
    save_hud_visible_widths(settings, hud_visible_widths_from_crops(normalized))
    settings.sync()
    return normalized


def load_hud_text_alignments(settings: QSettings) -> dict[str, str]:
    payload = settings.value(HUD_TEXT_ALIGNMENTS_SETTINGS_KEY, "", type=str).strip()
    if not payload:
        return default_hud_text_alignments()
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default_hud_text_alignments()
    return normalize_hud_text_alignments(raw if isinstance(raw, dict) else None)


def save_hud_text_alignments(
    settings: QSettings, alignments: Mapping[str, object] | None
) -> dict[str, str]:
    normalized = normalize_hud_text_alignments(alignments)
    settings.setValue(
        HUD_TEXT_ALIGNMENTS_SETTINGS_KEY,
        json.dumps(normalized, separators=(",", ":")),
    )
    settings.sync()
    return normalized


def load_hud_scales(settings: QSettings) -> dict[str, int]:
    payload = settings.value(HUD_SCALES_SETTINGS_KEY, "", type=str).strip()
    if not payload:
        has_existing_layout = bool(
            settings.value(HUD_SCREEN_LAYOUT_KEY, "", type=str).strip()
            or settings.value(HUD_SETTINGS_KEY, "", type=str).strip()
        )
        if has_existing_layout:
            return {spec.element_id: 100 for spec in HUD_ELEMENT_SPECS}
        return default_hud_scales()
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default_hud_scales()
    return normalize_hud_scales(raw if isinstance(raw, dict) else None)


def save_hud_scales(
    settings: QSettings, scales: Mapping[str, object] | None
) -> dict[str, int]:
    normalized = normalize_hud_scales(scales)
    settings.setValue(
        HUD_SCALES_SETTINGS_KEY,
        json.dumps(normalized, separators=(",", ":")),
    )
    settings.sync()
    return normalized


def load_hud_layout(
    settings: QSettings,
    visible_widths: Mapping[str, object] | None = None,
) -> dict[str, tuple[int, int]]:
    widths = (
        load_hud_visible_widths(settings)
        if visible_widths is None
        else normalize_hud_visible_widths(visible_widths)
    )
    payload = settings.value(HUD_SETTINGS_KEY, "", type=str).strip()
    if not payload:
        return normalize_hud_layout(default_hud_layout(), widths)
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return normalize_hud_layout(default_hud_layout(), widths)
    return normalize_hud_layout(raw if isinstance(raw, dict) else None, widths)


def save_hud_layout(
    settings: QSettings,
    layout: Mapping[str, object] | None,
    visible_widths: Mapping[str, object] | None = None,
) -> dict[str, tuple[int, int]]:
    widths = (
        load_hud_visible_widths(settings)
        if visible_widths is None
        else normalize_hud_visible_widths(visible_widths)
    )
    normalized = normalize_hud_layout(layout, widths)
    payload = {
        element_id: {"x": x, "y": y}
        for element_id, (x, y) in normalized.items()
    }
    settings.setValue(HUD_SETTINGS_KEY, json.dumps(payload, separators=(",", ":")))
    settings.sync()
    return normalized


def _place_missing_pc_clock(
    raw: Mapping[str, object],
    layout: dict[str, tuple[int, int]],
    crops: Mapping[str, object] | None,
    scales: Mapping[str, object] | None,
    screen_width: int,
    screen_height: int,
) -> dict[str, tuple[int, int]]:
    """Split the former combined location + PC clock block without a jump."""
    if "pc_clock" in raw:
        return layout
    normalized = dict(layout)
    normalized_crops = normalize_hud_crops(crops)
    widths = hud_visible_widths_from_crops(normalized_crops)
    normalized_scales = normalize_hud_scales(scales)
    location_spec = HUD_SPEC_BY_ID["location"]
    pc_spec = HUD_SPEC_BY_ID["pc_clock"]
    location_x, location_y = normalized["location"]
    location_height = scaled_hud_dimensions(
        location_spec, widths["location"], normalized_scales["location"]
    )[1]
    normalized["pc_clock"] = _bounded_position(
        pc_spec,
        location_x,
        location_y + location_height + 1,
        widths["pc_clock"],
        normalized_scales["pc_clock"],
        canvas_width=screen_width,
        canvas_height=screen_height,
    )
    return normalized


def _place_missing_guides(
    raw: Mapping[str, object],
    layout: dict[str, tuple[int, int]],
    crops: Mapping[str, object] | None,
    scales: Mapping[str, object] | None,
    screen_width: int,
    screen_height: int,
) -> dict[str, tuple[int, int]]:
    """Attach newly introduced lines to an existing 1.1.14 arrangement."""
    normalized = dict(layout)
    normalized_crops = normalize_hud_crops(crops)
    widths = hud_visible_widths_from_crops(normalized_crops)
    normalized_scales = normalize_hud_scales(scales)
    member_sets = {
        "guide_left": ("controls", "location", "pc_clock", "verse_clock"),
        "guide_right": ("radio_info", "media", "track"),
    }
    for guide_id, members in member_sets.items():
        if guide_id in raw:
            continue
        guide_spec = HUD_SPEC_BY_ID[guide_id]
        member_specs = [HUD_SPEC_BY_ID[member] for member in members]
        x = min(normalized[member][0] for member in members)
        bottom = max(
            normalized[member][1]
            + scaled_hud_dimensions(
                spec, widths[member], normalized_scales[member]
            )[1]
            for member, spec in zip(members, member_specs)
        )
        normalized[guide_id] = _bounded_position(
            guide_spec,
            x,
            bottom - 1,
            widths[guide_id],
            normalized_scales[guide_id],
            canvas_width=screen_width,
            canvas_height=screen_height,
        )
    return normalized


def load_hud_screen_layout(
    settings: QSettings,
    screen_width: int,
    screen_height: int,
    crops: Mapping[str, object] | None = None,
    scales: Mapping[str, object] | None = None,
) -> dict[str, tuple[int, int]]:
    normalized_crops = load_hud_crops(settings) if crops is None else normalize_hud_crops(crops)
    normalized_scales = load_hud_scales(settings) if scales is None else normalize_hud_scales(scales)
    payload = settings.value(HUD_SCREEN_LAYOUT_KEY, "", type=str).strip()
    if payload:
        try:
            raw = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            normalized = normalize_hud_screen_layout(
                raw, normalized_crops, screen_width, screen_height, normalized_scales
            )
            normalized = _place_missing_pc_clock(
                raw, normalized, normalized_crops, normalized_scales, screen_width, screen_height
            )
            return _place_missing_guides(
                raw, normalized, normalized_crops, normalized_scales, screen_width, screen_height
            )

    legacy_payload = settings.value(HUD_SETTINGS_KEY, "", type=str).strip()
    if not legacy_payload:
        return normalize_hud_screen_layout(
            default_hud_screen_layout(screen_width, screen_height),
            normalized_crops,
            screen_width,
            screen_height,
            normalized_scales,
        )

    # One-time transparent migration from the former 548 × 65 strip.
    legacy_widths = hud_visible_widths_from_crops(normalized_crops)
    legacy = load_hud_layout(settings, legacy_widths)
    origin_x = max(0, (int(screen_width) - HUD_CANVAS_WIDTH) // 2)
    origin_y = min(14, max(0, int(screen_height) - HUD_CANVAS_HEIGHT))
    migrated = {
        element_id: (origin_x + x, origin_y + y)
        for element_id, (x, y) in legacy.items()
    }
    return normalize_hud_screen_layout(
        migrated, normalized_crops, screen_width, screen_height, normalized_scales
    )


def save_hud_screen_layout(
    settings: QSettings,
    layout: Mapping[str, object] | None,
    crops: Mapping[str, object] | None,
    screen_width: int,
    screen_height: int,
    scales: Mapping[str, object] | None = None,
) -> dict[str, tuple[int, int]]:
    normalized = normalize_hud_screen_layout(
        layout, crops, screen_width, screen_height, scales
    )
    payload = {
        element_id: {"x": x, "y": y}
        for element_id, (x, y) in normalized.items()
    }
    settings.setValue(
        HUD_SCREEN_LAYOUT_KEY, json.dumps(payload, separators=(",", ":"))
    )
    settings.sync()
    return normalized


def normalize_hud_groups(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, Mapping):
        return {}
    normalized: dict[str, list[str]] = {}
    claimed: set[str] = set()
    for raw_name, raw_members in raw.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_members, Sequence) or isinstance(raw_members, (str, bytes)):
            continue
        members: list[str] = []
        for raw_member in raw_members:
            member = str(raw_member)
            if member in HUD_SPEC_BY_ID and member not in claimed:
                claimed.add(member)
                members.append(member)
        if len(members) >= 2:
            normalized[name] = members
    return normalized


def load_hud_groups(settings: QSettings) -> dict[str, list[str]]:
    payload = settings.value(HUD_GROUPS_SETTINGS_KEY, "", type=str).strip()
    if not payload:
        return {}
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return normalize_hud_groups(raw)


def save_hud_groups(settings: QSettings, groups: object) -> dict[str, list[str]]:
    normalized = normalize_hud_groups(groups)
    settings.setValue(
        HUD_GROUPS_SETTINGS_KEY,
        json.dumps(normalized, separators=(",", ":")),
    )
    settings.sync()
    return normalized


def make_hud_preview(
    layout: Mapping[str, object] | None,
    visible_widths: Mapping[str, object] | None,
) -> dict[str, object]:
    widths = normalize_hud_visible_widths(visible_widths)
    preview: dict[str, object] = dict(normalize_hud_layout(layout, widths))
    preview[HUD_PREVIEW_WIDTHS_KEY] = widths
    return preview


def make_hud_screen_preview(
    layout: Mapping[str, object] | None,
    crops: Mapping[str, object] | None,
    groups: object,
    screen_width: int,
    screen_height: int,
    scales: Mapping[str, object] | None = None,
    text_alignments: Mapping[str, object] | None = None,
) -> dict[str, object]:
    normalized_crops = normalize_hud_crops(crops)
    normalized_scales = normalize_hud_scales(scales)
    normalized_alignments = normalize_hud_text_alignments(text_alignments)
    preview: dict[str, object] = dict(
        normalize_hud_screen_layout(
            layout, normalized_crops, screen_width, screen_height, normalized_scales
        )
    )
    preview[HUD_PREVIEW_CROPS_KEY] = normalized_crops
    preview[HUD_PREVIEW_WIDTHS_KEY] = hud_visible_widths_from_crops(normalized_crops)
    preview[HUD_PREVIEW_GROUPS_KEY] = normalize_hud_groups(groups)
    preview[HUD_PREVIEW_SCALES_KEY] = normalized_scales
    preview[HUD_PREVIEW_TEXT_ALIGNMENTS_KEY] = normalized_alignments
    preview[HUD_PREVIEW_SCREEN_SIZE_KEY] = {
        "width": int(screen_width),
        "height": int(screen_height),
    }
    return preview


def reset_hud_layout(settings: QSettings) -> dict[str, tuple[int, int]]:
    for key in (
        HUD_SETTINGS_KEY,
        HUD_WIDTHS_SETTINGS_KEY,
        HUD_SCREEN_LAYOUT_KEY,
        HUD_CROPS_SETTINGS_KEY,
        HUD_GROUPS_SETTINGS_KEY,
        HUD_SCALES_SETTINGS_KEY,
        HUD_TEXT_ALIGNMENTS_SETTINGS_KEY,
    ):
        settings.remove(key)
    settings.sync()
    return default_hud_layout()
