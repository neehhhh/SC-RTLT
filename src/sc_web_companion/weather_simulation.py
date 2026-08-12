from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .verse_time import calculate_verse_time, calculate_verse_time_for_location


@dataclass(frozen=True, slots=True)
class WeatherDescriptor:
    key: str
    label: str
    compact_label: str


WEATHER_DESCRIPTORS: tuple[WeatherDescriptor, ...] = (
    WeatherDescriptor("sunny", "Soleil", "Soleil"),
    WeatherDescriptor("rain", "Pluie", "Pluie"),
    WeatherDescriptor("snow", "Neige", "Neige"),
    WeatherDescriptor("storm", "Orage", "Orage"),
    WeatherDescriptor("tempest", "Tempête", "Tempête"),
    WeatherDescriptor("air_bad", "Qualité de l’air mauvaise", "Air mauvais"),
)
WEATHER_BY_KEY = {item.key: item for item in WEATHER_DESCRIPTORS}


DEFAULT_WEIGHTS: dict[str, int] = {
    "sunny": 28,
    "rain": 16,
    "snow": 12,
    "storm": 16,
    "tempest": 12,
    "air_bad": 16,
}

LOCATION_WEIGHTS: dict[str, dict[str, int]] = {
    "new-babbage": {"sunny": 18, "rain": 8, "snow": 38, "storm": 10, "tempest": 18, "air_bad": 8},
    "lorville": {"sunny": 25, "rain": 4, "snow": 0, "storm": 15, "tempest": 20, "air_bad": 36},
    "area18": {"sunny": 23, "rain": 14, "snow": 0, "storm": 11, "tempest": 12, "air_bad": 40},
    "orison": {"sunny": 30, "rain": 18, "snow": 0, "storm": 20, "tempest": 24, "air_bad": 8},
    "daymar": {"sunny": 48, "rain": 2, "snow": 0, "storm": 10, "tempest": 34, "air_bad": 6},
    "yela": {"sunny": 22, "rain": 5, "snow": 42, "storm": 10, "tempest": 16, "air_bad": 5},
    "aberdeen": {"sunny": 34, "rain": 0, "snow": 0, "storm": 14, "tempest": 38, "air_bad": 14},
    "arial": {"sunny": 42, "rain": 2, "snow": 0, "storm": 12, "tempest": 34, "air_bad": 10},
    "calliope": {"sunny": 16, "rain": 6, "snow": 42, "storm": 10, "tempest": 18, "air_bad": 8},
    "clio": {"sunny": 16, "rain": 8, "snow": 38, "storm": 12, "tempest": 18, "air_bad": 8},
    "euterpe": {"sunny": 18, "rain": 12, "snow": 34, "storm": 12, "tempest": 16, "air_bad": 8},
}


DAY_PHASES = {"Aube", "Matin", "Midi", "Après-midi", "Soir"}
FULL_DAY_PHASES = {"Matin", "Midi", "Après-midi"}


def _bucket(moment: datetime) -> int:
    utc = moment.astimezone(timezone.utc)
    # One simulated weather state every two reference hours keeps the widget stable
    # while still feeling alive across a play session.
    return int(utc.timestamp() // (2 * 3600))


def _pick_weighted(location_id: str, bucket: int) -> str:
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(LOCATION_WEIGHTS.get(location_id, {}))
    total = sum(max(0, int(value)) for value in weights.values()) or 1
    digest = hashlib.sha256(f"{location_id}|{bucket}".encode("utf-8")).hexdigest()
    cursor = int(digest[:12], 16) % total
    running = 0
    for descriptor in WEATHER_DESCRIPTORS:
        running += max(0, int(weights.get(descriptor.key, 0)))
        if cursor < running:
            return descriptor.key
    return WEATHER_DESCRIPTORS[0].key


def simulate_weather(location_id: str, moment: datetime | None = None) -> dict[str, object]:
    base = calculate_verse_time(location_id, moment)
    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    phase = str(base.get("phase", ""))
    weather_key = _pick_weighted(location_id, _bucket(now))
    descriptor = WEATHER_BY_KEY[weather_key]
    is_daylight = phase in DAY_PHASES
    is_full_daylight = phase in FULL_DAY_PHASES
    display_label = descriptor.label
    compact_display = descriptor.compact_label
    if weather_key == "sunny" and not is_daylight:
        display_label = "Ciel clair"
        compact_display = "Ciel clair"
    return {
        **base,
        "weather": weather_key,
        "weather_label": descriptor.label,
        "weather_compact": descriptor.compact_label,
        "weather_compact_display": compact_display,
        "weather_display": display_label,
        "weather_source": "Simulation locale",
        "is_daylight": is_daylight,
        "is_full_daylight": is_full_daylight,
    }


def simulate_weather_for_location(
    location_name: str,
    visual_location_id: str,
    moment: datetime | None = None,
) -> dict[str, object]:
    """Decorative weather paired with an exact Astro Atlas location."""
    base = calculate_verse_time_for_location(location_name, moment)
    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    phase = str(base.get("phase", ""))
    weather_key = _pick_weighted(visual_location_id, _bucket(now))
    descriptor = WEATHER_BY_KEY[weather_key]
    is_daylight = phase in DAY_PHASES
    is_full_daylight = phase in FULL_DAY_PHASES
    display_label = descriptor.label
    compact_display = descriptor.compact_label
    if weather_key == "sunny" and not is_daylight:
        display_label = "Ciel clair"
        compact_display = "Ciel clair"
    return {
        **base,
        "location_id": visual_location_id,
        "weather": weather_key,
        "weather_label": descriptor.label,
        "weather_compact": descriptor.compact_label,
        "weather_compact_display": compact_display,
        "weather_display": display_label,
        "weather_source": "Simulation locale",
        "is_daylight": is_daylight,
        "is_full_daylight": is_full_daylight,
    }
