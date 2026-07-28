from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from PySide6.QtCore import QStandardPaths


@dataclass(frozen=True, slots=True)
class SiteDefinition:
    site_id: str
    name: str
    description: str
    url: str
    custom: bool = False


DEFAULT_SITES: tuple[SiteDefinition, ...] = (
    SiteDefinition("news", "News", "Actualités HCN Radio", "https://www.hcnradio.com/news"),
    SiteDefinition("wiki", "Star Citizen Wiki", "Vaisseaux, objets, lieux et documentation", "https://starcitizen.tools/"),
    SiteDefinition("ships", "Vaisseaux", "Tests, comparaison et performances via SPViewer", "https://www.spviewer.eu/"),
    SiteDefinition("cstone", "Item Finder", "Recherche de matériel et lieux de vente", "https://finder.cstone.space/"),
    SiteDefinition("trade-tools", "SC Trade Tools", "Routes commerciales et outils de transport", "https://sc-trade.tools/home"),
    SiteDefinition("uex", "UEX", "Commerce, routes et données communautaires", "https://uexcorp.space/"),
    SiteDefinition("spectrum", "Spectrum", "Forums et salons officiels Star Citizen", "https://robertsspaceindustries.com/spectrum/community/SC"),
    SiteDefinition("rsi", "RSI", "Site officiel de Star Citizen", "https://robertsspaceindustries.com/"),
)


def config_directory() -> Path:
    roaming = os.environ.get("APPDATA")
    if roaming:
        path = Path(roaming) / "PublicRealTimeChecker"
    else:
        path = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
    path.mkdir(parents=True, exist_ok=True)
    return path


def sites_file() -> Path:
    return config_directory() / "sites.json"


def save_sites(sites: Iterable[SiteDefinition]) -> None:
    payload = [asdict(site) for site in sites]
    sites_file().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_custom_id(name: str, url: str, existing: set[str]) -> str:
    host = urlsplit(url).hostname or name
    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-") or "site"
    candidate = f"custom-{slug}"
    counter = 2
    while candidate in existing:
        candidate = f"custom-{slug}-{counter}"
        counter += 1
    return candidate


def _upgrade_sites(sites: list[SiteDefinition]) -> list[SiteDefinition]:
    """Restore official sections while preserving valid user-added sites."""
    official_ids = {site.site_id for site in DEFAULT_SITES}
    result = list(DEFAULT_SITES)
    seen = set(official_ids)
    for site in sites:
        if site.site_id in official_ids or not site.custom:
            continue
        if not site.name.strip() or not site.url.strip():
            continue
        site_id = site.site_id if site.site_id not in seen else _safe_custom_id(site.name, site.url, seen)
        result.append(SiteDefinition(site_id, site.name.strip(), site.description.strip(), site.url.strip(), True))
        seen.add(site_id)
    return result


def load_sites() -> list[SiteDefinition]:
    path = sites_file()
    if not path.exists():
        save_sites(DEFAULT_SITES)
        return list(DEFAULT_SITES)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        sites = [
            SiteDefinition(
                site_id=str(item["site_id"]),
                name=str(item["name"]),
                description=str(item.get("description", "")),
                url=str(item["url"]),
                custom=bool(item.get("custom", str(item.get("site_id", "")).startswith("custom-"))),
            )
            for item in raw
            if isinstance(item, dict)
        ]
        upgraded = _upgrade_sites(sites)
        if upgraded != sites:
            save_sites(upgraded)
        return upgraded
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
        backup = path.with_suffix(".json.invalid")
        try:
            path.replace(backup)
        except OSError:
            pass
        save_sites(DEFAULT_SITES)
        return list(DEFAULT_SITES)


def add_custom_site(name: str, url: str, description: str = "Site personnalisé") -> SiteDefinition:
    sites = load_sites()
    existing = {site.site_id for site in sites}
    site = SiteDefinition(_safe_custom_id(name, url, existing), name.strip(), description.strip(), url.strip(), True)
    save_sites([*sites, site])
    return site


def remove_custom_site(site_id: str) -> bool:
    sites = load_sites()
    filtered = [site for site in sites if not (site.site_id == site_id and site.custom)]
    if len(filtered) == len(sites):
        return False
    save_sites(filtered)
    return True
