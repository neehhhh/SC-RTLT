from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque

from .verse_time import is_named_celestial_body, is_precise_verse_location, resolve_verse_location

_TIMESTAMP_RE = re.compile(rb"^<([^>]+Z)>")
_LOCATION_INVENTORY_RE = re.compile(
    rb"<RequestLocationInventory>\s+Player\[[^\]]+\]\s+requested inventory for Location\[([^\]]+)\]",
    re.IGNORECASE,
)
_INVENTORY_LOCATION_TRANSITION_RE = re.compile(
    rb"<Update Inventory Location>\s+Player\s*\[[^\]]+\]\s+is changing location\.\s+"
    rb"Landing\s+\[([0-9]+)\]\s+->\s+\[([0-9]+)\]\.\s+"
    rb"Location\s+\[([0-9]+)\]\s+->\s+\[([0-9]+)\]",
    re.IGNORECASE,
)
_STATION_STREAM_RE = re.compile(
    rb"(?:LocationManager(?:_rs_ext)?_|rs_ext_)((?:ARC|CRU|HUR|MIC)-(?:L[1-5]|LEO\d*))",
    re.IGNORECASE,
)
_ACTIVE_PLANET_RE = re.compile(
    rb"planet cells:\s+([1-9][0-9]*)\s+\[[^\]]+\].*?name:\s+([^\s]+)",
    re.IGNORECASE,
)
_ROOM_BODY_RE = re.compile(
    rb"RoomName:\s+(OOC_Stanton_[1-4](?:[a-d])?_[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_PROJECTED_START_RE = re.compile(
    rb"Projected Start Location is\s+(.+?)\s+for route to destination\s+(.+?)(?:\s+(?:Routing around|Obstructing Entity)|\s*[,;]|$)",
    re.IGNORECASE,
)
_QT_SELECTED_RE = re.compile(
    rb"Player has selected point\s+(.+?)\s+as their destination(?:\s*[,;]|\s|$)",
    re.IGNORECASE,
)
_QT_FUEL_RE = re.compile(
    rb"<Player Requested Fuel to Quantum Target - (?:Local|Server Routing)>.*?\bdestination\s+([^\s\],;]+)",
    re.IGNORECASE,
)
_QT_SURFACE_DESTINATION_RE = re.compile(
    rb"Adding surface location\s+(.+?)\s+to end of route",
    re.IGNORECASE,
)
_QT_SUCCESS_DESTINATION_RE = re.compile(
    rb"Successfully calculated route to\s+(.+?)\s+fuel estimate",
    re.IGNORECASE,
)
_SESSION_LOCATION_ID_RE = re.compile(rb"\blocationId\[([0-9]+)\]", re.IGNORECASE)

_MAX_LINE_BYTES = 1024 * 1024
_MAX_CANDIDATES = 500
_MAX_CANDIDATE_AGE_SECONDS = 15 * 60

_EVENT_PRIORITY: dict[str, int] = {
    "inventory_location_transition": 100,
    "request_location_inventory": 98,
    "location_manager_station": 96,
    "active_planet_cells": 84,
    "room_body": 80,
    "projected_route_start": 74,
    "session_location_id": 68,
    "surface_route_destination": 54,
    "starmap_selected": 44,
    "starmap_fuel_request": 40,
}


def public_parser_directory() -> Path:
    """Return the isolated directory that contains the one shareable registry file."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    path = root / "PublicRealTimeCheckerData" / "registry"
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_parser_output_path() -> Path:
    return public_parser_directory() / "Public_Real_Time_Checker_Registry.json"


@dataclass(frozen=True, slots=True)
class LocationCodeCandidate:
    observed_at_utc: str
    log_time: str
    event: str
    raw_token: str
    secondary_token: str
    resolved_name: str
    body: str
    confidence: str
    priority: int


class PublicParserRecorder:
    """Keep probable location codes in memory and write only manual Wi-Fi captures.

    The complete Game.log is never copied. No passive session file, diagnostic log,
    CSV report, player name, account identifier or absolute Game.log path is stored.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or public_parser_directory()
        self.output_path = self.root / "Public_Real_Time_Checker_Registry.json"
        if root is None:
            local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
            legacy_root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
            self.legacy_output_path = (
                legacy_root / "SC_RTLTData" / "public-parser" / "SC_RTLT_Public_Parser_Registry.json"
            )
        else:
            self.legacy_output_path = self.root / "SC_RTLT_Public_Parser_Registry.json"
        self._game_channel = ""
        self._candidates: Deque[tuple[float, LocationCodeCandidate]] = deque(maxlen=_MAX_CANDIDATES)
        self._last_signature = ""
        self._last_displayed_name = ""
        self._last_displayed_body = ""
        self._last_displayed_state = ""

    def start_session(self, game_log_path: Path | None = None) -> None:
        self._game_channel = game_log_path.parent.name if game_log_path is not None else ""
        self._candidates.clear()
        self._last_signature = ""

    def close_session(self) -> None:
        self._candidates.clear()
        self._last_signature = ""

    def observe_display(self, name: str, body: str, state: str) -> None:
        self._last_displayed_name = str(name or "")
        self._last_displayed_body = str(body or "")
        self._last_displayed_state = str(state or "")

    def observe_line(self, line: bytes | str) -> tuple[LocationCodeCandidate, ...]:
        payload = line.encode("utf-8", errors="replace") if isinstance(line, str) else line
        if len(payload) > _MAX_LINE_BYTES:
            return ()
        log_time = self._extract_log_time(payload)
        matches: list[tuple[str, str, str]] = []

        transition = _INVENTORY_LOCATION_TRANSITION_RE.search(payload)
        if transition is not None:
            matches.append(
                (
                    "inventory_location_transition",
                    self._decode(transition.group(4)),
                    f"previous_location:{self._decode(transition.group(3))}",
                )
            )

        inventory = _LOCATION_INVENTORY_RE.search(payload)
        if inventory is not None:
            matches.append(("request_location_inventory", self._decode(inventory.group(1)), ""))

        station = _STATION_STREAM_RE.search(payload)
        if station is not None:
            matches.append(("location_manager_station", self._decode(station.group(1)), ""))

        active_planet = _ACTIVE_PLANET_RE.search(payload)
        if active_planet is not None:
            matches.append(
                (
                    "active_planet_cells",
                    self._decode(active_planet.group(2)),
                    f"cell_count:{self._decode(active_planet.group(1))}",
                )
            )

        room = _ROOM_BODY_RE.search(payload)
        if room is not None:
            matches.append(("room_body", self._decode(room.group(1)), ""))

        projected = _PROJECTED_START_RE.search(payload)
        if projected is not None:
            matches.append(
                (
                    "projected_route_start",
                    self._decode(projected.group(1)),
                    self._decode(projected.group(2)),
                )
            )

        session_location = _SESSION_LOCATION_ID_RE.search(payload)
        if session_location is not None:
            matches.append(("session_location_id", self._decode(session_location.group(1)), ""))

        surface = _QT_SURFACE_DESTINATION_RE.search(payload)
        if surface is not None:
            matches.append(("surface_route_destination", self._decode(surface.group(1)), ""))
        else:
            selected = _QT_SELECTED_RE.search(payload)
            if selected is not None:
                matches.append(("starmap_selected", self._decode(selected.group(1)), ""))
            fuel = _QT_FUEL_RE.search(payload)
            if fuel is not None:
                matches.append(("starmap_fuel_request", self._decode(fuel.group(1)), ""))
            success = _QT_SUCCESS_DESTINATION_RE.search(payload)
            if success is not None:
                matches.append(("surface_route_destination", self._decode(success.group(1)), ""))

        recorded: list[LocationCodeCandidate] = []
        for event, raw_token, secondary_token in matches:
            raw_token = self._clean_token(raw_token)
            if not raw_token:
                continue
            signature = f"{log_time}|{event}|{raw_token}|{secondary_token}"
            if signature == self._last_signature:
                continue
            self._last_signature = signature
            resolved = resolve_verse_location(raw_token)
            if resolved is None:
                confidence = "unresolved"
                resolved_name = ""
                body = ""
            elif is_precise_verse_location(resolved):
                confidence = "exact"
                resolved_name = resolved.name
                body = resolved.body
            elif is_named_celestial_body(resolved):
                confidence = "parent_body"
                resolved_name = resolved.name
                body = resolved.body
            else:
                confidence = "generic"
                resolved_name = resolved.name
                body = resolved.body
            candidate = LocationCodeCandidate(
                observed_at_utc=datetime.now(timezone.utc).isoformat(),
                log_time=log_time,
                event=event,
                raw_token=raw_token,
                secondary_token=self._clean_token(secondary_token),
                resolved_name=resolved_name,
                body=body,
                confidence=confidence,
                priority=_EVENT_PRIORITY[event],
            )
            self._candidates.append((time.monotonic(), candidate))
            recorded.append(candidate)
        return tuple(recorded)

    def best_candidate(self) -> tuple[LocationCodeCandidate | None, float | None]:
        now = time.monotonic()
        eligible: list[tuple[float, LocationCodeCandidate, float]] = []
        for observed_at, candidate in self._candidates:
            age = max(0.0, now - observed_at)
            if age > _MAX_CANDIDATE_AGE_SECONDS:
                continue
            # Event strength is the main signal. Resolution is only a small
            # tie-breaker so a newer physical inventory transition is not
            # replaced by an older, already-known location name.
            resolution_bonus = 1.0 if candidate.confidence == "exact" else 0.5 if candidate.confidence == "parent_body" else 0.0
            score = float(candidate.priority) + resolution_bonus - (age / 60.0)
            eligible.append((score, candidate, age))
        if not eligible:
            return None, None
        eligible.sort(key=lambda item: (item[0], item[1].observed_at_utc), reverse=True)
        _, candidate, age = eligible[0]
        return candidate, age

    def confirm_location(self, label: str) -> dict[str, object]:
        clean_label = " ".join(str(label or "").split()).strip()
        if not clean_label:
            return {"saved": False, "reason": "empty_label"}

        candidate, age = self.best_candidate()
        if candidate is None:
            return {"saved": False, "reason": "no_recent_location_code"}

        now = datetime.now(timezone.utc).isoformat()
        record: dict[str, object] = {
            "record_id": uuid.uuid4().hex,
            "captured_at_utc": now,
            "user_location": clean_label,
            "location_code": candidate.raw_token,
            "source_event": candidate.event,
            "source_confidence": candidate.confidence,
            "game_log_time": candidate.log_time,
            "candidate_age_seconds": round(float(age or 0.0), 3),
            "resolved_name": candidate.resolved_name,
            "resolved_body": candidate.body,
            "displayed_name": self._last_displayed_name,
            "displayed_body": self._last_displayed_body,
            "displayed_state": self._last_displayed_state,
            "game_channel": self._game_channel,
        }

        try:
            payload = self._load_registry()
            records = payload.get("records")
            if not isinstance(records, list):
                records = []
            records.append(record)
            payload = {
                "schema_version": 1,
                "application": "Public Real Time Checker",
                "updated_at_utc": now,
                "privacy": "Manual labels and structured location codes only. Game.log is read locally and is never copied.",
                "records": records[-5000:],
            }
            self.root.mkdir(parents=True, exist_ok=True)
            temp_path = self.output_path.with_suffix(".json.tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self.output_path)
        except OSError as exc:
            return {
                "saved": False,
                "reason": "write_error",
                "error": str(exc),
                "location_code": candidate.raw_token,
            }

        return {
            "saved": True,
            "reason": "saved",
            "location_code": candidate.raw_token,
            "source_event": candidate.event,
            "source_confidence": candidate.confidence,
            "output_path": str(self.output_path),
            "record": record,
        }

    def load_confirmed_mappings(self) -> dict[str, dict[str, str]]:
        """Load only the curated mappings bundled with the application."""
        mappings: dict[str, dict[str, str]] = {}
        seed_path = Path(__file__).resolve().parent / "assets" / "location_mappings.json"
        try:
            payload = json.loads(seed_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return mappings
        records = payload.get("mappings") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return mappings
        for record in records:
            if not isinstance(record, dict):
                continue
            token = str(record.get("raw_token") or "").strip()
            name = str(record.get("name") or "").strip()
            if not token or not name:
                continue
            mappings[token] = {
                "name": name,
                "body": str(record.get("body") or ""),
                "clock_mode": str(record.get("clock_mode") or "utc"),
                "location_type": str(record.get("location_type") or "Curated location"),
                "source": str(record.get("source") or "bundled_registry"),
            }
        return mappings

    def _load_registry(self) -> dict[str, object]:
        source_path = self.output_path
        if not source_path.exists() and self.legacy_output_path.exists():
            source_path = self.legacy_output_path
        if not source_path.exists():
            return {"records": []}
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"records": []}
        return payload if isinstance(payload, dict) else {"records": []}

    @staticmethod
    def _clean_token(value: str) -> str:
        return " ".join(str(value or "").replace("\x00", " ").split()).strip(" \t\r\n,;[]\"'")

    @staticmethod
    def _decode(value: bytes) -> str:
        return value.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _extract_log_time(payload: bytes) -> str:
        match = _TIMESTAMP_RE.search(payload)
        if match is None:
            return ""
        return match.group(1).decode("ascii", errors="ignore")
