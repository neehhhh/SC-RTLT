from __future__ import annotations

import csv
import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True, slots=True)
class BodyRecord:
    name: str
    body_type: str
    parent_star: str
    x: float
    y: float
    z: float
    radius: float
    rotation_hours: float
    rotation_correction: float


@dataclass(frozen=True, slots=True)
class LocationRecord:
    name: str
    parent_body: str
    parent_star: str
    location_type: str
    x: float
    y: float
    z: float
    quantum: bool = False
    reference_clock: bool = False


@dataclass(frozen=True, slots=True)
class VerseClockLocation:
    location_id: str
    label: str
    body: str
    verse_name: str | None = None
    kind: str = "surface"


@dataclass(frozen=True, slots=True)
class ResolvedVerseLocation:
    """A location name resolved against the bundled VerseTime Astro Atlas."""

    name: str
    body: str
    raw_name: str
    exact_location: bool = True
    location_type: str = ""
    parent_star: str = ""
    reference_clock: bool = False


VERSE_LOCATIONS: tuple[VerseClockLocation, ...] = (
    VerseClockLocation("new-babbage", "New Babbage", "microTech", "New Babbage"),
    VerseClockLocation("lorville", "Lorville", "Hurston", "Lorville"),
    VerseClockLocation("area18", "Area18", "ArcCorp", "Area18"),
    VerseClockLocation("orison", "Orison", "Crusader", "Orison"),
    VerseClockLocation("daymar", "Daymar", "Daymar"),
    VerseClockLocation("yela", "Yela", "Yela"),
    VerseClockLocation("aberdeen", "Aberdeen", "Aberdeen"),
    VerseClockLocation("arial", "Arial", "Arial"),
    VerseClockLocation("calliope", "Calliope", "Calliope"),
    VerseClockLocation("clio", "Clio", "Clio"),
    VerseClockLocation("euterpe", "Euterpe", "Euterpe"),
)
LOCATION_BY_ID = {item.location_id: item for item in VERSE_LOCATIONS}
LEGACY_LOCATION_MIGRATIONS: dict[str, str] = {
    "port-tressler": "new-babbage",
    "everus": "lorville",
}


def normalize_location_id(location_id: str) -> str:
    """Map removed orbital-station choices to their nearest supported city."""
    candidate = LEGACY_LOCATION_MIGRATIONS.get(str(location_id or ""), str(location_id or ""))
    return candidate if candidate in LOCATION_BY_ID else "new-babbage"


def _asset_root() -> Path:
    return Path(__file__).resolve().parent / "assets" / "versetime"


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def load_verse_data() -> tuple[dict[str, BodyRecord], dict[str, LocationRecord]]:
    bodies: dict[str, BodyRecord] = {}
    with (_asset_root() / "bodies.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            bodies[name] = BodyRecord(
                name=name,
                body_type=str(row.get("type", "")).strip(),
                parent_star=str(row.get("parentStar", "")).strip(),
                x=_float(row.get("coordinateX")),
                y=_float(row.get("coordinateY")),
                z=_float(row.get("coordinateZ")),
                radius=_float(row.get("bodyRadius")),
                rotation_hours=_float(row.get("rotationRate")),
                rotation_correction=_float(row.get("rotationCorrection")),
            )

    locations: dict[str, LocationRecord] = {}
    with (_asset_root() / "locations.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            locations[name] = LocationRecord(
                name=name,
                parent_body=str(row.get("parentBody", "")).strip(),
                parent_star=str(row.get("parentStar", "")).strip(),
                location_type=str(row.get("type", "")).strip(),
                x=_float(row.get("coordinateX")),
                y=_float(row.get("coordinateY")),
                z=_float(row.get("coordinateZ")),
                quantum=str(row.get("quantum", "")).strip() in {"1", "true", "True"},
            )

    # VerseTime currently covers Stanton and Pyro. This small offline supplement
    # adds the named Nyx ports visible in the current game data. Nyx does not yet
    # expose reliable solar-rotation data here, so these entries use a clearly
    # marked reference clock instead of a fabricated local solar calculation.
    nyx_names = (
        "Levski",
        "People's Service Station Alpha",
        "People's Service Station Delta",
        "People's Service Station Lambda",
        "People's Service Station Theta",
        "Pyro Gateway",
        "Stanton Gateway",
        "Transit Point Glaciem Alpha",
        "Transit Point Glaciem Bravo",
        "Transit Point Glaciem Charlie",
        "QV Breaker Station BRK-127",
        "QV Breaker Station BRK-184",
        "QV Breaker Station BRK-204",
        "QV Breaker Station BRK-235",
        "QV Breaker Station BRK-267",
        "QV Breaker Station BRK-284",
        "QV Breaker Station BRK-304",
        "QV Breaker Station BRK-320",
        "QV Breaker Station BRK-425",
        "QV Breaker Station BRK-437",
        "QV Breaker Station BRK-521",
        "QV Breaker Station BRK-542",
        "QV Breaker Station BRK-546",
        "QV Breaker Station BRK-563",
        "QV Breaker Station BRK-608",
        "QV Breaker Station BRK-711",
        "QV Breaker Station BRK-782",
        "QV Breaker Station BRK-879",
        "QV Breaker Station BRK-970",
        "QV Breaker Station BRK-985",
    )
    for name in nyx_names:
        locations.setdefault(
            name,
            LocationRecord(
                name=name,
                parent_body="Delamar" if name == "Levski" else "Nyx",
                parent_star="Nyx",
                location_type="Manmade",
                x=0.0,
                y=0.0,
                z=0.0,
                quantum=True,
                reference_clock=True,
            ),
        )
    return bodies, locations


def _mod(value: float, divisor: float) -> float:
    return value % divisor


def _phase(hour: int) -> str:
    if hour < 5:
        return "Nuit"
    if hour < 8:
        return "Aube"
    if hour < 12:
        return "Matin"
    if hour < 15:
        return "Midi"
    if hour < 19:
        return "Après-midi"
    if hour < 22:
        return "Soir"
    return "Nuit"



_BODY_THEME_IDS: dict[str, str] = {
    "microTech": "new-babbage",
    "Calliope": "calliope",
    "Clio": "clio",
    "Euterpe": "euterpe",
    "Hurston": "lorville",
    "Aberdeen": "aberdeen",
    "Arial": "arial",
    "Ita": "lorville",
    "Magda": "lorville",
    "ArcCorp": "area18",
    "Lyria": "area18",
    "Wala": "area18",
    "Crusader": "orison",
    "Cellin": "daymar",
    "Daymar": "daymar",
    "Yela": "yela",
    "Delamar": "daymar",
    "Nyx": "new-babbage",
}

_ORBITAL_BODY_FALLBACKS: dict[str, str] = {
    "ARC": "ArcCorp",
    "CRU": "Crusader",
    "HUR": "Hurston",
    "MIC": "microTech",
    "PYR1": "Pyro I",
    "PYR2": "Monox",
    "PYR3": "Bloom",
    "PYR5": "Pyro V",
    "PYR6": "Terminus",
}


def _search_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", ascii_text.casefold())


@lru_cache(maxsize=1)
def _atlas_aliases() -> tuple[tuple[str, LocationRecord], ...]:
    _, locations = load_verse_data()
    aliases = [(_search_key(record.name), record) for record in locations.values()]
    aliases.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(aliases)


@lru_cache(maxsize=1)
def _body_aliases() -> tuple[tuple[str, BodyRecord], ...]:
    bodies, _ = load_verse_data()
    aliases = [(_search_key(record.name), record) for record in bodies.values() if record.name not in {"Stanton", "Pyro"}]
    aliases.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(aliases)


def _atlas_alias_matches(key: str, alias: str) -> bool:
    if not alias:
        return False
    if key == alias or key.endswith(alias):
        return True
    if len(alias) < 5:
        return False
    index = key.find(alias)
    if index < 0:
        return False

    # Numbered families must not collapse into a shorter existing member.
    # Examples: PAF-IV is not PAF-I, and ASD Onyx S1A11 is not S1A1.
    tail = key[index + len(alias):]
    numbered_family = re.search(
        r"(?:paf(?:i|ii|iii)|s[1-9][a-z][0-9]+)$", alias, re.IGNORECASE
    )
    if tail and numbered_family is not None and tail[0].isalnum():
        return False
    return True


_INTERNAL_LOCATION_ALIASES: dict[str, str] = {
    # 4.9 location-inventory identifiers used by the orbital stations.
    "rrarcleo": "Baijini Point",
    "rrcruleo": "Seraphim Station",
    "rrhurleo": "Everus Harbor",
    "rrmicleo": "Port Tressler",
    "rrjpstantonpyro": "Pyro Gateway (Stanton)",
    "locrsextstanpyrojp1": "Pyro Gateway (Stanton)",
    # 4.9 technical surface token whose public location exists in VerseTime.
    "abcollectorgasstanton1": "Ludlow",
}


_INTERNAL_BODY_ALIASES: dict[str, str] = {
    "stanton1": "Hurston",
    "stanton1a": "Arial",
    "stanton1b": "Aberdeen",
    "stanton1c": "Magda",
    "stanton1d": "Ita",
    "stanton2": "Crusader",
    "stanton2a": "Cellin",
    "stanton2b": "Daymar",
    "stanton2c": "Yela",
    "stanton3": "ArcCorp",
    "stanton3a": "Lyria",
    "stanton3b": "Wala",
    "stanton4": "microTech",
    "stanton4a": "Calliope",
    "stanton4b": "Clio",
    "stanton4c": "Euterpe",
}


_GENERIC_BODY_FALLBACKS: dict[str, str] = {
    "s1": "Hurston",
    "s1a": "Arial",
    "s1b": "Aberdeen",
    "s1c": "Magda",
    "s1d": "Ita",
    "s2": "Crusader",
    "s2a": "Cellin",
    "s2b": "Daymar",
    "s2c": "Yela",
    "s3": "ArcCorp",
    "s3a": "Lyria",
    "s3b": "Wala",
    "s4": "microTech",
    "s4a": "Calliope",
    "s4b": "Clio",
    "s4c": "Euterpe",
}


_STATION_ALIAS_TOKENS: tuple[tuple[str, str], ...] = (
    ("rrarcleo", "RR_ARC_LEO"),
    ("rrcruleo", "RR_CRU_LEO"),
    ("rrhurleo", "RR_HUR_LEO"),
    ("rrmicleo", "RR_MIC_LEO"),
    ("locrrs1l1", "HUR-L1"),
    ("locrrs1l2", "HUR-L2"),
    ("locrrs1l3", "HUR-L3"),
    ("locrrs1l4", "HUR-L4"),
    ("locrrs1l5", "HUR-L5"),
    ("locrrs2l1", "CRU-L1"),
    ("locrrs2l2", "CRU-L2"),
    ("locrrs2l3", "CRU-L3"),
    ("locrrs2l4", "CRU-L4"),
    ("locrrs2l5", "CRU-L5"),
    ("locrrs3l1", "ARC-L1"),
    ("locrrs3l2", "ARC-L2"),
    ("locrrs3l3", "ARC-L3"),
    ("locrrs3l4", "ARC-L4"),
    ("locrrs3l5", "ARC-L5"),
    ("locrrs4l1", "MIC-L1"),
    ("locrrs4l2", "MIC-L2"),
    ("locrrs4l3", "MIC-L3"),
    ("locrrs4l4", "MIC-L4"),
    ("locrrs4l5", "MIC-L5"),
)

# Exact public station names from the bundled VerseTime locations.csv.
# CRU-L2 and CRU-L3 currently have no Rest Stop record in that dataset.
_LAGRANGE_STATION_NAMES: dict[str, str] = {
    "HUR-L1": "Green Glade Station",
    "HUR-L2": "Faithful Dream Station",
    "HUR-L3": "Thundering Express Station",
    "HUR-L4": "Melodic Fields Station",
    "HUR-L5": "High Course Station",
    "CRU-L1": "Ambitious Dream Station",
    "CRU-L4": "Shallow Fields Station",
    "CRU-L5": "Beautiful Glen Station",
    "ARC-L1": "Wide Forest Station",
    "ARC-L2": "Lively Pathway Station",
    "ARC-L3": "Modern Express Station",
    "ARC-L4": "Faint Glen Station",
    "ARC-L5": "Yellow Core Station",
    "MIC-L1": "Shallow Frontier Station",
    "MIC-L2": "Long Forest Station",
    "MIC-L3": "Endless Odyssey Station",
    "MIC-L4": "Red Crossroads Station",
    "MIC-L5": "Modern Icarus Station",
}



def _resolved_from_location_record(record: LocationRecord, raw: str) -> ResolvedVerseLocation:
    return ResolvedVerseLocation(
        record.name,
        record.parent_body,
        raw,
        True,
        record.location_type,
        record.parent_star,
        record.reference_clock,
    )


def _resolved_named_location(name: str, raw: str) -> ResolvedVerseLocation | None:
    _, locations = load_verse_data()
    record = locations.get(name)
    if record is None:
        return None
    resolved = _resolved_from_location_record(record, raw)
    return ResolvedVerseLocation(
        resolved.name,
        resolved.body,
        raw,
        resolved.exact_location,
        resolved.location_type,
        resolved.parent_star,
        resolved.reference_clock,
    )


def _resolved_from_body_name(body_name: str, raw: str) -> ResolvedVerseLocation | None:
    bodies, _ = load_verse_data()
    body = bodies.get(body_name)
    if body is None:
        return None
    return ResolvedVerseLocation(
        body.name,
        body.name,
        raw,
        False,
        "Body",
        body.parent_star,
        False,
    )


def _generic_resolved(
    name: str,
    body: str,
    raw: str,
    *,
    exact_location: bool = True,
    location_type: str,
    reference_clock: bool,
) -> ResolvedVerseLocation:
    bodies, _ = load_verse_data()
    body_record = bodies.get(body)
    parent_star = body_record.parent_star if body_record is not None else ""
    return ResolvedVerseLocation(
        name,
        body,
        raw,
        exact_location,
        location_type,
        parent_star,
        reference_clock,
    )


def _resolve_station_alias(raw: str, key: str) -> ResolvedVerseLocation | None:
    if not key:
        return None

    # Planetary orbital stations. These aliases existed in 1.0.3 and are kept
    # explicit so a generic spatial fallback can never override their name.
    orbital_aliases = {
        "rrarcleo": "Baijini Point",
        "rrcruleo": "Seraphim Station",
        "rrhurleo": "Everus Harbor",
        "rrmicleo": "Port Tressler",
        "rsextarcleo1": "Baijini Point",
        "rsextcruleo1": "Seraphim Station",
        "rsexthurleo1": "Everus Harbor",
        "rsextmicleo1": "Port Tressler",
    }
    for token, public_name in orbital_aliases.items():
        if token in key:
            return _resolved_named_location(public_name, raw)

    direct_leo = re.fullmatch(r"(arc|cru|hur|mic)leo[0-9]*", key)
    if direct_leo is not None:
        public_name = {
            "arc": "Baijini Point",
            "cru": "Seraphim Station",
            "hur": "Everus Harbor",
            "mic": "Port Tressler",
        }[direct_leo.group(1)]
        return _resolved_named_location(public_name, raw)

    # Lagrange Rest Stops. Resolve directly to the public VerseTime record rather
    # than first resolving the Lagrange body and then guessing the nearest station.
    rr_match = re.search(r"locrrs([1-4])l([1-5])", key)
    if rr_match is not None:
        prefix = {"1": "HUR", "2": "CRU", "3": "ARC", "4": "MIC"}[rr_match.group(1)]
        code = f"{prefix}-L{rr_match.group(2)}"
        station_name = _LAGRANGE_STATION_NAMES.get(code)
        if station_name:
            return _resolved_named_location(station_name, raw)
        return _resolved_from_body_name(code, raw)

    rs_match = re.search(r"rsext(arc|cru|hur|mic)(leo)?([1-5])", key)
    if rs_match is not None:
        prefix = rs_match.group(1).upper()
        if rs_match.group(2):
            public_name = {
                "ARC": "Baijini Point",
                "CRU": "Seraphim Station",
                "HUR": "Everus Harbor",
                "MIC": "Port Tressler",
            }[prefix]
            return _resolved_named_location(public_name, raw)
        code = f"{prefix}-L{rs_match.group(3)}"
        station_name = _LAGRANGE_STATION_NAMES.get(code)
        if station_name:
            return _resolved_named_location(station_name, raw)
        return _resolved_from_body_name(code, raw)
    return None


def _resolve_body_alias_from_key(raw: str, key: str) -> ResolvedVerseLocation | None:
    internal_body = _INTERNAL_BODY_ALIASES.get(key)
    if internal_body is not None:
        return _resolved_from_body_name(internal_body, raw)

    # Preserve identifier segment boundaries. The previous compact substring match
    # treated the C in CommArray/Crusader as the moon suffix in Stanton4c/Stanton2c.
    # Examples fixed here:
    #   OOC_Stanton4_CommArray  -> microTech, not Euterpe
    #   OOC_Stanton_2_Crusader -> Crusader, not Yela
    raw_key = str(raw or "").casefold()
    match = re.search(
        r"stanton[_-]?([1-4])(?:[_-]?([a-d])(?=[_-]|$))?",
        raw_key,
    )
    if match is not None:
        compact = f"stanton{match.group(1)}{match.group(2) or ''}"
        internal_body = _INTERNAL_BODY_ALIASES.get(compact)
        if internal_body is not None:
            return _resolved_from_body_name(internal_body, raw)

    # Some short synthetic tokens use S1/S1a style segments. Require a boundary
    # after the optional moon letter for the same reason.
    short_match = re.search(r"(?:^|[_-])s([1-4])([a-d])?(?=[_-]|$)", raw_key)
    if short_match is not None:
        short_key = f"s{short_match.group(1)}{short_match.group(2) or ''}"
        body_name = _GENERIC_BODY_FALLBACKS.get(short_key)
        if body_name is not None:
            return _resolved_from_body_name(body_name, raw)

    # Object-container names introduced in 4.9 can abbreviate Stanton to ST.
    # Keep strict separators so words such as ``stash`` are never mistaken for ST4.
    st_match = re.search(r"(?:^|[_-])(?:oc[_-]?)?st([1-4])([a-d])?(?=[_-]|$)", raw_key)
    if st_match is not None:
        short_key = f"s{st_match.group(1)}{st_match.group(2) or ''}"
        body_name = _GENERIC_BODY_FALLBACKS.get(short_key)
        if body_name is not None:
            return _resolved_from_body_name(body_name, raw)

    # Dynamic settlement prefixes identify a physical planetary environment even
    # when the public settlement name is absent from Game.log.
    for prefix, body_name in (
        ("hurdyn", "Hurston"),
        ("arcdyn", "ArcCorp"),
        ("micdyn", "microTech"),
        ("crudyn", "Crusader"),
    ):
        if key.startswith(prefix):
            return _resolved_from_body_name(body_name, raw)
    return None


def _resolve_structured_surface_alias(raw: str, key: str) -> ResolvedVerseLocation | None:
    """Resolve compact 4.9 surface identifiers against VerseTime when possible.

    Game.log often removes words such as ``Mining Facility`` from public names.
    The stable site code (for example SMCa-8) and the parent body are still
    present, so match those two facts instead of inventing a name.
    """
    body = _resolve_body_alias_from_key(raw, key)
    if body is None or not is_named_celestial_body(body):
        return None

    _, locations = load_verse_data()
    body_name = body.name
    code_match = re.search(r"(sm[a-z]{1,3}[0-9]+)", key)
    if code_match is not None:
        code = code_match.group(1)
        candidates = [
            record
            for record in locations.values()
            if record.parent_body.casefold() == body_name.casefold()
            and code in _search_key(record.name)
        ]
        if len(candidates) == 1:
            return _resolved_from_location_record(candidates[0], raw)

    # Other structured surface tokens can contain a distinctive public suffix.
    # Require both the parent body and at least two significant words to avoid
    # turning a weak guess into a trusted VerseTime match.
    significant = [
        token
        for token in re.findall(r"[a-z]+|[0-9]+", str(raw or "").casefold())
        if len(token) >= 4 and token not in {"ooc", "stanton", "surface", "location"}
    ]
    if len(significant) >= 2:
        candidates = []
        for record in locations.values():
            if record.parent_body.casefold() != body_name.casefold():
                continue
            record_key = _search_key(record.name)
            if all(_search_key(token) in record_key for token in significant[-2:]):
                candidates.append(record)
        if len(candidates) == 1:
            return _resolved_from_location_record(candidates[0], raw)
    return None


def _is_probable_surface_site_token(raw: str, key: str) -> bool:
    """Return True for a planetary site token, never for a bare body or space mine."""
    compact = str(key or "")
    if not compact or "abmine" in compact or compact.startswith("navpointdynamic"):
        return False
    bare_bodies = set(_INTERNAL_BODY_ALIASES)
    stripped = re.sub(r"^(?:ooc|objectcontainer)", "", compact)
    if compact in bare_bodies or stripped in bare_bodies:
        return False
    return any(
        marker in compact
        for marker in (
            "hurdyn", "arcdyn", "micdyn", "crudyn", "collector", "drlct",
            "settlement", "outpost", "surface", "sfce", "shubin", "hdms",
            "processing", "facility", "stash", "cluster",
            "paf", "planetaryalignment", "asd", "airspacedefense",
        )
    )


def unresolved_surface_destination(raw: str, body_name: str = "") -> ResolvedVerseLocation:
    """Represent an explicit surface-route destination whose public name is unknown.

    The body is optional because an opaque NavPoint can be selected before the log
    reveals its planet or moon. The widget must still stop showing the old city.
    """
    bodies, _ = load_verse_data()
    body = bodies.get(str(body_name or "").strip())
    return ResolvedVerseLocation(
        "No data available",
        body.name if body is not None else str(body_name or "").strip(),
        str(raw or "").strip(),
        True,
        "Unknown site",
        body.parent_star if body is not None else "",
        True,
    )


def provisional_surface_location(raw: str, body: ResolvedVerseLocation | None) -> ResolvedVerseLocation | None:
    """Represent an unknown surface site without inventing a public name."""
    if body is None or not is_named_celestial_body(body):
        return None
    key = _search_key(raw)
    if not _is_probable_surface_site_token(raw, key):
        return None
    return _generic_resolved(
        "No data available",
        body.name,
        raw,
        exact_location=True,
        location_type="Unknown site",
        reference_clock=True,
    )


def _resolve_generic_game_token(raw: str, key: str) -> ResolvedVerseLocation | None:
    station = _resolve_station_alias(raw, key)
    if station is not None:
        return station

    structured_surface = _resolve_structured_surface_alias(raw, key)
    if structured_surface is not None:
        return structured_surface

    if key in {"newbabbageloc", "lorvilleloc", "area18loc", "orisonloc"}:
        suffix_map = {
            "newbabbageloc": "New Babbage",
            "lorvilleloc": "Lorville",
            "area18loc": "Area18",
            "orisonloc": "Orison",
        }
        _, locations = load_verse_data()
        record = locations.get(suffix_map[key])
        if record is not None:
            return _resolved_from_location_record(record, raw)

    comm_array_match = re.search(r"(stanton[1-4][a-d]?|s[1-4][a-d]?)commarray", key)
    if comm_array_match is not None:
        alias = comm_array_match.group(1)
        body_name = _INTERNAL_BODY_ALIASES.get(alias) or _GENERIC_BODY_FALLBACKS.get(alias)
        if body_name is None and alias.startswith('s'):
            body_name = _GENERIC_BODY_FALLBACKS.get(alias)
        if body_name is not None:
            return _generic_resolved(
                "Comm Array",
                body_name,
                raw,
                location_type="Comm Array",
                reference_clock=True,
            )

    if "abmine" in key:
        body_match = re.search(r"(stanton[1-4][a-d]?|s[1-4][a-d]?)", key)
        body_name = None
        if body_match is not None:
            alias = body_match.group(1)
            body_name = _INTERNAL_BODY_ALIASES.get(alias) or _GENERIC_BODY_FALLBACKS.get(alias)
        if body_name is not None:
            return _generic_resolved(
                "Asteroid Mining Base",
                body_name,
                raw,
                location_type="Asteroid mining base",
                reference_clock=True,
            )

    # Resolve any physical parent before applying generic space labels. Surface
    # clusters such as hurdyn_cluster_* are settlements on Hurston, not asteroid
    # fields. Returning the parent body is deliberately conservative: VerseTime
    # remains authoritative for the public name and local clock.
    body = _resolve_body_alias_from_key(raw, key)
    if body is not None:
        provisional = provisional_surface_location(raw, body)
        return provisional or body

    if "cluster" in key or "asteroid" in key:
        body_name = None
        for token, candidate in (
            ("arccorp", "ArcCorp"),
            ("stanton3", "ArcCorp"),
            ("hurston", "Hurston"),
            ("hurdyn", "Hurston"),
            ("microtech", "microTech"),
            ("stanton4", "microTech"),
            ("crusader", "Crusader"),
            ("stanton2", "Crusader"),
        ):
            if token in key:
                body_name = candidate
                break
        if body_name is not None:
            return _resolved_from_body_name(body_name, raw)

    # A dynamic nav point is only an opaque routing node. It does not prove that
    # the player is in deep space and must never overwrite a known planet, moon or
    # station. The state machine keeps the last reliable environment instead.
    if key.startswith("navpointdynamic"):
        return None
    return None


def resolve_verse_location(raw_name: str) -> ResolvedVerseLocation | None:
    """Resolve a Game.log location token without using any network service.

    Game.log commonly reports internal identifiers such as ``Stanton2_Orison``.
    The matcher compares the compacted suffix with the bundled Astro Atlas and
    deliberately ignores ordinary log lines; callers must first validate the
    event type.
    """
    raw = str(raw_name or "").strip().strip("[]\"'")
    key = _search_key(raw)
    if not key or key in {"invalid", "invalidlocationid", "none", "unknown"}:
        return None

    for alias, record in _atlas_aliases():
        if _atlas_alias_matches(key, alias):
            return _resolved_from_location_record(record, raw)

    internal_location = _INTERNAL_LOCATION_ALIASES.get(key)
    if internal_location:
        _, locations = load_verse_data()
        record = locations.get(internal_location)
        if record is not None:
            return _resolved_from_location_record(record, raw)

    generic_token = _resolve_generic_game_token(raw, key)
    if generic_token is not None:
        return generic_token

    internal_body = _INTERNAL_BODY_ALIASES.get(key)
    if internal_body is None:
        # 4.9 often wraps the same identifiers in OOC_/ObjectContainer tokens.
        # Match the longest body marker present anywhere in the compact token so
        # OOC_Stanton4_CommArray still resolves to the correct parent body.
        for internal_key in sorted(_INTERNAL_BODY_ALIASES, key=len, reverse=True):
            if internal_key in key:
                internal_body = _INTERNAL_BODY_ALIASES[internal_key]
                break
    if internal_body:
        body_resolved = _resolved_from_body_name(internal_body, raw)
        if body_resolved is not None:
            return body_resolved

    for alias, body in _body_aliases():
        if alias and (key == alias or key.endswith(alias)):
            return ResolvedVerseLocation(
                body.name,
                body.name,
                raw,
                False,
                body.__class__.__name__.replace("Record", ""),
                body.parent_star,
                False,
            )
    return None


_GENERIC_LOCATION_TYPES = {
    "star", "planet", "moon", "asteroid", "asteroid field", "asteroid belt",
    "anomaly", "jump point", "pointofinterest",
}


def is_precise_verse_location(resolved: ResolvedVerseLocation | None) -> bool:
    """Return True only for a named local destination suitable for the widget."""
    if resolved is None or not resolved.exact_location:
        return False
    kind = str(resolved.location_type or "").strip().casefold().replace("_", " ")
    if kind in _GENERIC_LOCATION_TYPES:
        return False
    key = _search_key(resolved.name)
    return bool(key) and not key.startswith(("asteroidcluster", "om", "orbitalmarker"))


def is_named_celestial_body(resolved: ResolvedVerseLocation | None) -> bool:
    """Allow a confirmed planet or moon, but never a whole star system."""
    if resolved is None or resolved.exact_location:
        return False
    kind = str(resolved.location_type or "").strip().casefold().replace("_", " ")
    if kind not in {"body", "planet", "moon"}:
        return False
    key = _search_key(resolved.name)
    return bool(key) and key not in {"stanton", "pyro", "nyx"}


LOW_ORBIT_MAX_RADIUS_RATIO = 1.25
_ORBITAL_LOCATION_TYPES = {"space station", "orbital laser platform"}
_REFERENCE_LOCATION_TYPES = {
    "commarray", "asteroid cluster", "asteroid mining base", "navigation point",
}


def astro_atlas_locations() -> tuple[LocationRecord, ...]:
    """Expose the 516 bundled Astro Atlas records in stable name order.

    The separate Nyx offline supplement is deliberately excluded so callers can
    distinguish sourced Atlas data from provisional reference-clock entries.
    """
    _, locations = load_verse_data()
    atlas_records = (record for record in locations.values() if not record.reference_clock)
    return tuple(sorted(atlas_records, key=lambda item: item.name.casefold()))


def astro_atlas_location_count() -> int:
    """Return the number of sourced named locations bundled from Astro Atlas."""
    return len(astro_atlas_locations())


def _atlas_record_for_resolved(
    resolved: ResolvedVerseLocation | None,
) -> LocationRecord | None:
    if resolved is None or not resolved.exact_location:
        return None
    _, locations = load_verse_data()
    record = locations.get(resolved.name)
    if record is None:
        return None
    if record.parent_body.casefold() != str(resolved.body or "").casefold():
        return None
    return record


def is_co_rotating_orbital_location(
    resolved: ResolvedVerseLocation | None,
) -> bool:
    """Return True for a low orbital site fixed to a rotating planet or moon.

    Astro Atlas stores these positions in the parent body's rotating frame. A
    radius ratio limit prevents distant stations, Lagrange rest stops and deep
    space structures from being given a fabricated local solar time.
    """
    if resolved is None or resolved.reference_clock:
        return False
    record = _atlas_record_for_resolved(resolved)
    if record is None or record.location_type.strip().casefold() not in _ORBITAL_LOCATION_TYPES:
        return False
    bodies, _ = load_verse_data()
    body = bodies.get(record.parent_body)
    if body is None or body.rotation_hours <= 0 or body.radius <= 0:
        return False
    orbital_radius = math.sqrt(record.x * record.x + record.y * record.y + record.z * record.z)
    if orbital_radius <= body.radius:
        return False
    return orbital_radius / body.radius <= LOW_ORBIT_MAX_RADIUS_RATIO


def location_clock_model(resolved: ResolvedVerseLocation | None) -> str:
    """Classify how the widget may display time for an Atlas location."""
    if resolved is None or resolved.reference_clock or is_named_celestial_body(resolved):
        return "reference"

    kind = str(resolved.location_type or "").strip().casefold().replace("_", " ")
    compact_kind = re.sub(r"[^a-z0-9]+", "", kind)
    body_key = _search_key(resolved.body)
    name_key = _search_key(resolved.name)

    if re.match(r"^(?:arc|cru|hur|mic)l[1-5]", body_key):
        return "reference"
    if re.match(r"^pyr\d+l[1-5]", body_key):
        return "reference"
    if "jumppoint" in compact_kind or "jumpoint" in compact_kind or "jp" in body_key:
        return "reference"
    if kind in _REFERENCE_LOCATION_TYPES or compact_kind in {
        "commarray", "asteroidcluster", "asteroidminingbase", "navigationpoint",
    }:
        return "reference"
    if compact_kind in {"space", "deepspace"} or name_key == "deepspace":
        return "reference"

    record = _atlas_record_for_resolved(resolved)
    if record is not None and record.location_type.strip().casefold() in _ORBITAL_LOCATION_TYPES:
        return "co_rotating_orbit" if is_co_rotating_orbital_location(resolved) else "reference"

    bodies, _ = load_verse_data()
    body = bodies.get(str(resolved.body or ""))
    if resolved.exact_location and body is not None and body.rotation_hours > 0:
        return "surface"
    return "reference"


def location_uses_utc_clock(resolved: ResolvedVerseLocation | None) -> bool:
    """Use the spatial reference clock outside surface and low synchronous orbit."""
    return location_clock_model(resolved) == "reference"


@lru_cache(maxsize=128)
def nearest_named_station(body_name: str) -> ResolvedVerseLocation | None:
    """Resolve a generic Lagrange target to its unique named station, if any."""
    _, locations = load_verse_data()
    candidates = [
        record for record in locations.values()
        if record.parent_body.casefold() == str(body_name or "").casefold()
        and record.location_type.casefold() in {"space station", "manmade"}
        and record.quantum
    ]
    if len(candidates) != 1:
        return None
    record = candidates[0]
    return ResolvedVerseLocation(
        record.name,
        record.parent_body,
        body_name,
        True,
        record.location_type,
        record.parent_star,
        record.reference_clock,
    )


def same_destination_body(destination: ResolvedVerseLocation, arrived: ResolvedVerseLocation) -> bool:
    """Check whether a body-only quantum arrival confirms a precise route target."""
    if arrived.exact_location:
        return destination.name.casefold() == arrived.name.casefold()
    target_body = str(destination.body or "").casefold()
    arrived_body = str(arrived.body or arrived.name or "").casefold()
    return bool(target_body and target_body == arrived_body)


def visual_location_id_for_body(body_name: str) -> str:
    """Choose an existing decorative widget theme for an Atlas body."""
    if body_name in _BODY_THEME_IDS:
        return _BODY_THEME_IDS[body_name]
    upper = str(body_name or "").upper()
    for prefix, fallback_body in _ORBITAL_BODY_FALLBACKS.items():
        if upper.startswith(prefix):
            return _BODY_THEME_IDS.get(fallback_body, "new-babbage")
    return "new-babbage"


def body_is_moon(body_name: str) -> bool:
    """Return whether the bundled Atlas classifies this body as a moon."""
    bodies, _ = load_verse_data()
    body = bodies.get(str(body_name or "").strip())
    return body is not None and body.body_type.casefold() == "moon"


def _rotating_body_name(body_name: str, bodies: dict[str, BodyRecord]) -> str:
    body = bodies.get(body_name)
    if body is not None and body.rotation_hours > 0:
        return body_name
    upper = str(body_name or "").upper()
    for prefix, fallback in _ORBITAL_BODY_FALLBACKS.items():
        if upper.startswith(prefix) and fallback in bodies:
            return fallback
    raise ValueError(f"Données VerseTime sans rotation exploitable pour {body_name}")


def _calculate_for_resolved_location(
    resolved: ResolvedVerseLocation,
    moment: datetime | None = None,
) -> dict[str, object]:
    bodies, locations = load_verse_data()
    clock_model = location_clock_model(resolved)
    if clock_model == "reference":
        now = moment or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        local_seconds = now.hour * 3600 + now.minute * 60 + now.second
        nyx_reference = resolved.reference_clock and resolved.parent_star.casefold() == "nyx"
        return {
            "location_id": visual_location_id_for_body(resolved.body),
            "location": resolved.name,
            "body": resolved.body,
            "atlas_parent_body": resolved.body,
            "local_time": f"{now.hour:02d}:{now.minute:02d}",
            "local_time_seconds": local_seconds,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
            "phase": _phase(now.hour),
            "source": "Nyx offline supplement" if nyx_reference else "VerseTime Astro Atlas",
            "reference": "Heure de référence Nyx" if nyx_reference else "Heure spatiale de référence",
            "location_kind": "reference",
            "clock_model": clock_model,
            "raw_location": resolved.raw_name,
        }
    body_name = _rotating_body_name(resolved.body, bodies)
    body = bodies[body_name]

    star = bodies.get(body.parent_star or "Stanton") or bodies.get("Stanton")
    if star is None:
        raise ValueError("Étoile parente introuvable dans les données VerseTime")

    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    elapsed_days = (now - EPOCH).total_seconds() / SECONDS_PER_DAY
    length_of_day_days = body.rotation_hours / 24.0
    current_cycle = elapsed_days / length_of_day_days
    body_hour_angle = _mod(
        360.0 - _mod(current_cycle, 1.0) * 360.0 - body.rotation_correction,
        360.0,
    )
    stationary_noon_longitude = math.degrees(
        _mod(math.atan2(star.y - body.y, star.x - body.x) - math.pi / 2.0, 2.0 * math.pi)
    )

    verse_record = locations.get(resolved.name) if resolved.exact_location else None
    if verse_record is not None and verse_record.parent_body == body_name:
        longitude_360 = math.degrees(_mod(math.atan2(verse_record.y, verse_record.x), 2.0 * math.pi))
    else:
        longitude_360 = 0.0

    hour_angle = _mod(
        body_hour_angle - _mod(longitude_360 - stationary_noon_longitude, 360.0),
        360.0,
    )
    if hour_angle > 180.0:
        hour_angle -= 360.0

    local_seconds = SECONDS_PER_DAY * ((360.0 - (hour_angle + 180.0)) / 360.0)
    local_seconds = int(round(local_seconds)) % int(SECONDS_PER_DAY)
    hour, remainder = divmod(local_seconds, 3600)
    minute, second = divmod(remainder, 60)
    return {
        "location_id": visual_location_id_for_body(body_name),
        "location": resolved.name,
        "body": body_name,
        "atlas_parent_body": resolved.body,
        "local_time": f"{hour:02d}:{minute:02d}",
        "local_time_seconds": local_seconds,
        "hour": hour,
        "minute": minute,
        "second": second,
        "phase": _phase(hour),
        "source": "VerseTime Astro Atlas",
        "reference": (
            "Heure orbitale synchronisée"
            if clock_model == "co_rotating_orbit"
            else "Heure solaire locale SC"
        ),
        "location_kind": clock_model,
        "clock_model": clock_model,
        "raw_location": resolved.raw_name,
    }


def calculate_verse_time_for_location(
    location_name: str,
    moment: datetime | None = None,
) -> dict[str, object]:
    resolved = resolve_verse_location(location_name)
    if resolved is None:
        raise ValueError(f"Lieu absent de l’Astro Atlas VerseTime : {location_name}")
    return _calculate_for_resolved_location(resolved, moment)

def calculate_verse_time(
    location_id: str,
    moment: datetime | None = None,
) -> dict[str, object]:
    """Calculate a Star Citizen local solar time using VerseTime's public data.

    This intentionally exposes only time-of-day information. It does not fabricate
    live weather, temperature, wind, visibility, or shard telemetry.
    """
    location = LOCATION_BY_ID[normalize_location_id(location_id)]
    bodies, locations = load_verse_data()
    body = bodies.get(location.body)
    if body is None or body.rotation_hours <= 0:
        raise ValueError(f"Données VerseTime absentes pour {location.body}")

    star = bodies.get(body.parent_star or "Stanton") or bodies.get("Stanton")
    if star is None:
        raise ValueError("Étoile parente introuvable dans les données VerseTime")

    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    elapsed_days = (now - EPOCH).total_seconds() / SECONDS_PER_DAY
    length_of_day_days = body.rotation_hours / 24.0
    current_cycle = elapsed_days / length_of_day_days

    body_hour_angle = _mod(
        360.0 - _mod(current_cycle, 1.0) * 360.0 - body.rotation_correction,
        360.0,
    )
    stationary_noon_longitude = math.degrees(
        _mod(math.atan2(star.y - body.y, star.x - body.x) - math.pi / 2.0, 2.0 * math.pi)
    )

    verse_record = locations.get(location.verse_name or "")
    if verse_record is not None and verse_record.parent_body == location.body:
        longitude_360 = math.degrees(_mod(math.atan2(verse_record.y, verse_record.x), 2.0 * math.pi))
    else:
        # Whole-body selections use VerseTime's prime meridian as a stable reference.
        longitude_360 = 0.0

    hour_angle = _mod(
        body_hour_angle - _mod(longitude_360 - stationary_noon_longitude, 360.0),
        360.0,
    )
    if hour_angle > 180.0:
        hour_angle -= 360.0

    local_seconds = SECONDS_PER_DAY * ((360.0 - (hour_angle + 180.0)) / 360.0)
    local_seconds = int(round(local_seconds)) % int(SECONDS_PER_DAY)
    hour, remainder = divmod(local_seconds, 3600)
    minute, second = divmod(remainder, 60)

    return {
        "location_id": location.location_id,
        "location": location.label,
        "body": location.body,
        "local_time": f"{hour:02d}:{minute:02d}",
        "local_time_seconds": local_seconds,
        "hour": hour,
        "minute": minute,
        "second": second,
        "phase": _phase(hour),
        "source": "VerseTime",
        "reference": "Heure locale SC",
        "location_kind": location.kind,
    }
