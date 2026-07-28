from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VehicleHudPalette:
    manufacturer_id: str
    display_name: str
    accent: str
    highlight: str
    deep: str
    effect: str = "orbit"


@dataclass(frozen=True, slots=True)
class VehicleContextUpdate:
    manufacturer_id: str
    vehicle_code: str


# At foot, in an unknown vehicle, and for RSI, the HUD keeps the approved
# New Babbage palette. Anvil is deliberately provisional until a model-specific
# palette is defined from an observed ship.
DEFAULT_VEHICLE_PALETTE = VehicleHudPalette(
    "", "New Babbage", "#7fd9ee", "#e5fbff", "#102c42", "ice"
)

VEHICLE_HUD_PALETTES: dict[str, VehicleHudPalette] = {
    "aegis": VehicleHudPalette(
        "aegis", "Aegis Dynamics", "#55cbe8", "#ddfbff", "#102f3d", "orbit"
    ),
    "anvil": VehicleHudPalette(
        "anvil", "Anvil Aerospace", "#7fd9ee", "#e5fbff", "#102c42", "ice"
    ),
    "aopoa": VehicleHudPalette(
        "aopoa", "Aopoa", "#bfd7dd", "#f6ffff", "#304047", "mist"
    ),
    "argo": VehicleHudPalette(
        "argo", "ARGO Astronautics", "#d49a32", "#ffe2a0", "#3b2911", "industrial"
    ),
    "banu": VehicleHudPalette(
        "banu", "Banu Souli", "#8ed8f5", "#edfbff", "#173645", "mist"
    ),
    "cnou": VehicleHudPalette(
        "cnou", "Consolidated Outland", "#ad832a", "#ffe29a", "#33260e", "industrial"
    ),
    "crusader": VehicleHudPalette(
        "crusader", "Crusader Industries", "#3d8fd2", "#bceaff", "#0c2543", "orbit"
    ),
    "drake": VehicleHudPalette(
        "drake", "Drake Interplanetary", "#d5792a", "#ffd0a0", "#3a1d0d", "industrial"
    ),
    "esperia": VehicleHudPalette(
        "esperia", "Esperia", "#d24a4a", "#ffd0ca", "#3a1114", "heat"
    ),
    "gatac": VehicleHudPalette(
        "gatac", "Gatac Manufacture", "#7350c5", "#f7f4ff", "#21133d", "mist"
    ),
    "greys-market": VehicleHudPalette(
        "greys-market", "Grey’s Market", "#6f7b47", "#dce2b9", "#202619", "industrial"
    ),
    "kruger": VehicleHudPalette(
        "kruger", "Kruger Intergalactic", "#70ac80", "#fff0a6", "#183024", "orbit"
    ),
    "mirai": VehicleHudPalette(
        "mirai", "Mirai", "#4b58c6", "#cdbbff", "#15183e", "orbit"
    ),
    "misc": VehicleHudPalette(
        "misc", "MISC", "#3ba59f", "#f4d569", "#102f32", "industrial"
    ),
    "origin": VehicleHudPalette(
        "origin", "Origin Jumpworks", "#278def", "#f6fbff", "#0e2943", "orbit"
    ),
    "rsi": VehicleHudPalette(
        "rsi", "Roberts Space Industries", "#7fd9ee", "#e5fbff", "#102c42", "ice"
    ),
}

# Internal entity prefixes observed in Star Citizen data and logs. Extra aliases
# are harmless because a token is accepted only in the entity field directly
# attached to CSCItemNavigation.
_MANUFACTURER_BY_PREFIX = {
    "AEGS": "aegis",
    "ANVL": "anvil",
    "AOPO": "aopoa",
    "AOPOA": "aopoa",
    "XIAN": "aopoa",
    "ARGO": "argo",
    "BANU": "banu",
    "CNOU": "cnou",
    "CRUS": "crusader",
    "DRAK": "drake",
    "ESPR": "esperia",
    "GAMA": "gatac",
    "GATC": "gatac",
    "GATAC": "gatac",
    "GREY": "greys-market",
    "GRMK": "greys-market",
    "GRIN": "greys-market",
    "KRIG": "kruger",
    "MRAI": "mirai",
    "MISC": "misc",
    "ORIG": "origin",
    "RSI": "rsi",
}

_CSC_ENTITY_RE = re.compile(
    rb"\|\s*([^|\r\n]+?)\s*\|\s*CSCItemNavigation::([A-Za-z0-9_:<>~]+)",
    re.IGNORECASE,
)
_INSTANCE_ID_RE = re.compile(r"(?:_[0-9]{5,})?(?:\[[0-9]+\])?$", re.IGNORECASE)
_REJECTED_ENTITY_MARKERS = (
    "asop",
    "display",
    "elevator",
    "hangar",
    "loadingplatform",
    "preview",
    "showroom",
    "tube",
)
_INACTIVE_ENTITY_NAMES = {
    "null",
    "null entity",
    "none",
    "invalid",
    "invalid entity",
}


def vehicle_hud_palette(
    manufacturer_id: str | None, vehicle_code: str | None = None
) -> VehicleHudPalette:
    del vehicle_code  # Reserved for future Anvil model-specific palettes.
    key = str(manufacturer_id or "").strip().casefold()
    return VEHICLE_HUD_PALETTES.get(key, DEFAULT_VEHICLE_PALETTE)


def manufacturer_from_vehicle_code(vehicle_code: str | None) -> str:
    code = str(vehicle_code or "").strip()
    if not code:
        return ""
    prefix = code.split("_", 1)[0].upper()
    return _MANUFACTURER_BY_PREFIX.get(prefix, "")


def _clean_vehicle_code(entity_field: str) -> str:
    text = entity_field.strip().strip('"\'')
    text = _INSTANCE_ID_RE.sub("", text)
    return text.strip()


class VehicleContextParser:
    """Read only the entity directly bound to Star Citizen item navigation."""

    def parse_line(self, line: bytes | str) -> VehicleContextUpdate | None:
        payload = line.encode("utf-8", errors="replace") if isinstance(line, str) else line
        if b"cscitemnavigation::" not in payload.lower():
            return None
        match = _CSC_ENTITY_RE.search(payload)
        if match is None:
            return None

        entity_field = match.group(1).decode("utf-8", errors="replace").strip()
        method = match.group(2).decode("ascii", errors="ignore").casefold()
        folded = entity_field.casefold()
        if any(marker in folded for marker in _REJECTED_ENTITY_MARKERS):
            return None

        if folded in _INACTIVE_ENTITY_NAMES:
            # PostInitialize commonly logs NULL ENTITY during setup or route
            # rerouting. Only a direct route query is a useful at-foot signal.
            if "getstarmaproutesegmentdata" in method:
                return VehicleContextUpdate("", "")
            return None

        vehicle_code = _clean_vehicle_code(entity_field)
        manufacturer_id = manufacturer_from_vehicle_code(vehicle_code)
        if not manufacturer_id:
            return None
        return VehicleContextUpdate(manufacturer_id, vehicle_code)
