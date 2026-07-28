from __future__ import annotations

import re
from typing import Protocol


class SettingsLike(Protocol):
    def value(self, key: str, defaultValue=None, type=None): ...  # noqa: A002


def normalize_language(value: object) -> str:
    language = str(value or "fr").strip().casefold().replace("_", "-")
    return "en" if language.startswith("en") else "fr"


def current_language(settings: SettingsLike | None) -> str:
    if settings is None:
        return "fr"
    try:
        return normalize_language(settings.value("app/language", "fr", type=str))
    except (AttributeError, TypeError, ValueError):
        return "fr"


def tr(settings: SettingsLike | None, french: str, english: str) -> str:
    return english if current_language(settings) == "en" else french


def translate_weather(weather_key: str, *, daylight: bool, language: str) -> str:
    key = str(weather_key or "").strip().casefold()
    labels = {
        "fr": {
            "sunny": "Soleil" if daylight else "Ciel clair",
            "rain": "Pluie",
            "snow": "Neige",
            "storm": "Orage",
            "tempest": "Tempête",
            "air_bad": "Qualité de l’air mauvaise",
        },
        "en": {
            "sunny": "Sunny" if daylight else "Clear sky",
            "rain": "Rain",
            "snow": "Snow",
            "storm": "Storm",
            "tempest": "Tempest",
            "air_bad": "Poor air quality",
        },
    }
    selected = labels[normalize_language(language)]
    return selected.get(key, str(weather_key or ""))


def translate_location_name(name: str, language: str) -> str:
    text = str(name or "").strip()
    if normalize_language(language) != "en" or not text:
        return text

    upper = text.upper()
    exact = {
        "AUCUNE DONNÉE": "NO DATA AVAILABLE",
        "AUCUNE DONNÉE DISPONIBLE": "NO DATA AVAILABLE",
        "NO DATA": "NO DATA AVAILABLE",
        "NO DATA AVAILABLE": "NO DATA AVAILABLE",
        "ESPACE PROFOND": "DEEP SPACE",
        "DEEP SPACE": "DEEP SPACE",
    }
    if upper in exact:
        return exact[upper]

    atmosphere = re.fullmatch(
        r"ATMOSPH[ÈE]RE(?:\s+DE)?\s+(.+)", text, flags=re.IGNORECASE
    )
    if atmosphere:
        return f"{atmosphere.group(1)} Atmosphere"
    site = re.fullmatch(r"SITE\s*[–-]\s*(.+)", text, flags=re.IGNORECASE)
    if site:
        return f"Site - {site.group(1)}"
    return text


_OFFICIAL_SITE_TEXT: dict[str, tuple[str, str, str, str]] = {
    "news": ("News", "News", "Actualités HCN Radio", "HCN Radio news"),
    "wiki": ("Star Citizen Wiki", "Star Citizen Wiki", "Vaisseaux, objets, lieux et documentation", "Ships, items, locations and documentation"),
    "ships": ("Vaisseaux", "Ships", "Tests, comparaison et performances via SPViewer", "Tests, comparisons and performance via SPViewer"),
    "cstone": ("Item Finder", "Item Finder", "Recherche de matériel et lieux de vente", "Find equipment and sales locations"),
    "trade-tools": ("SC Trade Tools", "SC Trade Tools", "Routes commerciales et outils de transport", "Trade routes and hauling tools"),
    "uex": ("UEX", "UEX", "Commerce, routes et données communautaires", "Trading, routes and community data"),
    "spectrum": ("Spectrum", "Spectrum", "Forums et salons officiels Star Citizen", "Official Star Citizen forums and channels"),
    "rsi": ("RSI", "RSI", "Site officiel de Star Citizen", "Official Star Citizen website"),
}


def site_name(site_id: str, fallback: str, language: str) -> str:
    entry = _OFFICIAL_SITE_TEXT.get(str(site_id))
    if entry is None:
        return fallback
    return entry[1] if normalize_language(language) == "en" else entry[0]


def site_description(site_id: str, fallback: str, language: str) -> str:
    entry = _OFFICIAL_SITE_TEXT.get(str(site_id))
    if entry is None:
        return fallback
    return entry[3] if normalize_language(language) == "en" else entry[2]
