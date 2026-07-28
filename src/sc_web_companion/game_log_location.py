from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterable

from .public_parser_recorder import PublicParserRecorder, public_parser_directory, public_parser_output_path
from .vehicle_palette import VehicleContextParser, VehicleContextUpdate

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from .verse_time import (
    ResolvedVerseLocation,
    is_named_celestial_body,
    is_precise_verse_location,
    location_uses_utc_clock,
    nearest_named_station,
    resolve_verse_location,
    unresolved_surface_destination,
    same_destination_body,
)


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
_STAMINA_ROOM_BODY_RE = re.compile(
    rb"RoomName:\s+(OOC_Stanton_[1-4](?:[a-d])?_[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_ACTIVE_PLANET_CELLS_RE = re.compile(
    rb"planet cells:\s+([1-9][0-9]*)\s+\[[^\]]+\].*?name:\s+(OOC_Stanton_[1-4](?:[a-d])?_[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_JURISDICTION_ENTER_RE = re.compile(
    rb'Added notification "Entered (Hurston Dynamics|ArcCorp|microTech|Crusader(?: Industries)?|UEE) Jurisdiction',
    re.IGNORECASE,
)
_QT_TARGET_SELECTED_RE = re.compile(
    rb"Player has selected point\s+(.+?)\s+as their destination(?:\s*[,;]|\s|$)",
    re.IGNORECASE,
)
_QT_FUEL_TARGET_RE = re.compile(
    rb"<Player Requested Fuel to Quantum Target - (?:Local|Server Routing)>.*?\bdestination\s+([^\s\],;]+)",
    re.IGNORECASE,
)
_QT_ROUTE_DESTINATION_RE = re.compile(
    rb"while routing from\s+.+?\s+to\s+(.+?)\s+(?:Routing around|Obstructing Entity)",
    re.IGNORECASE,
)
_QT_PROJECTED_DESTINATION_RE = re.compile(
    rb"Projected Start Location is\s+.+?\s+for route to destination\s+(.+?)(?:\s+(?:Routing around|Obstructing Entity)|\s*[,;]|$)",
    re.IGNORECASE,
)
_QT_PROJECTED_START_RE = re.compile(
    rb"Projected Start Location is\s+(.+?)\s+for route to destination\s+.+?(?:\s+(?:Routing around|Obstructing Entity)|\s*[,;]|$)",
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
_STATION_STREAM_RE = re.compile(
    rb"(?:LocationManager(?:_rs_ext)?_|rs_ext_)((?:ARC|CRU|HUR|MIC)-(?:L[1-5]|LEO\d*))",
    re.IGNORECASE,
)
_QT_ARRIVED_RE = re.compile(
    rb"Quantum Drive has arrived at final destination",
    re.IGNORECASE,
)
_ARMISTICE_ENTERED_RE = re.compile(
    rb'(?:Added notification|Notification)\s+"(?:Entering|Entered) Armistice Zone',
    re.IGNORECASE,
)
_ARMISTICE_LEFT_RE = re.compile(
    rb'(?:Added notification|Notification)\s+"Leaving Armistice Zone',
    re.IGNORECASE,
)
_QT_NO_ROUTE_RE = re.compile(
    rb"<Failed to get starmap route data!>.*?No Route loaded!",
    re.IGNORECASE,
)
_QT_CANNOT_INITIATE_RE = re.compile(
    rb"Quantum Travel:.*?cannot be initiated",
    re.IGNORECASE,
)
_EXITED_MONITORED_ZONE_RE = re.compile(
    rb"\b(?:Exited|Leaving|Left)\s+(?:a\s+)?monitored\s+(?:zone|space)\b",
    re.IGNORECASE,
)
_ENTERED_MONITORED_ZONE_RE = re.compile(
    rb"\b(?:Entered|Entering)\s+(?:a\s+)?monitored\s+(?:zone|space)\b",
    re.IGNORECASE,
)
_TIMESTAMP_RE = re.compile(rb"^<([^>]+Z)>")

_CHANNELS = ("LIVE", "PTU", "EPTU", "TECH-PREVIEW")
_MAX_RECOVERY_BYTES = 2 * 1024 * 1024
_MAX_READ_BYTES = 512 * 1024
_MAX_LINE_BYTES = 1024 * 1024
_PENDING_MAX_AGE_SECONDS = 60 * 60
_STATION_HINT_MAX_AGE_SECONDS = 30.0
_RECENT_ARRIVAL_GUARD_SECONDS = 120.0
_MAP_CLOSE_SUPPRESSION_SECONDS = 3.0

_LOCAL_ORBITAL_STATIONS = {
    "hurston": "Everus Harbor",
    "crusader": "Seraphim Station",
    "arccorp": "Baijini Point",
    "microtech": "Port Tressler",
}


@dataclass(frozen=True, slots=True)
class GameLocationDetection:
    name: str
    body: str
    raw_location: str
    location_type: str = ""
    clock_mode: str = "local"
    travel_state: str = "location"


@dataclass(frozen=True, slots=True)
class GameLocationUpdate:
    detection: GameLocationDetection
    confirmed: bool


@dataclass(frozen=True, slots=True)
class GameLocationDiagnostic:
    event: str
    raw_token: str
    resolved_name: str
    body: str
    confidence: str
    log_time: str


@dataclass(frozen=True, slots=True)
class _PendingDestination:
    resolved: ResolvedVerseLocation
    source: str
    log_time: datetime | None
    observed_at: float


class GameLogLocationParser:
    """Extract confirmed locations plus temporary travel transitions."""

    def __init__(self, confirmed_mappings: dict[str, dict[str, str]] | None = None) -> None:
        self._confirmed_mappings: dict[str, dict[str, str]] = dict(confirmed_mappings or {})
        self._station_hint: _PendingDestination | None = None
        self._recent_arrival: GameLocationDetection | None = None
        self._recent_arrival_at = 0.0
        self._route_destination: _PendingDestination | None = None
        self._quantum_target: _PendingDestination | None = None
        self._quantum_target_seen = False
        self._quantum_raw_target = ""
        self._travel_preview_active = False
        self._map_preview_active = False
        self._active_destination: ResolvedVerseLocation | None = None
        self._journey_active = False
        self._preview_suppressed = False
        self._preview_suppressed_at = 0.0
        self._left_armistice_since_fuel = False
        # Physical state is deliberately separate from Starmap previews.
        # A clicked destination must never become the fallback used by Escape/F2.
        self._physical_position: GameLocationDetection | None = None
        self._last_confirmed: GameLocationDetection | None = None
        self._map_session_open = False
        self._current_jurisdiction = ""
        self._monitored_state = "unknown"
        self._diagnostics: list[GameLocationDiagnostic] = []

    def reset(self, *, clear_confirmed: bool = False) -> None:
        self._clear_navigation_state()
        self._station_hint = None
        self._recent_arrival = None
        self._recent_arrival_at = 0.0
        self._diagnostics.clear()
        if clear_confirmed:
            self._physical_position = None
            self._last_confirmed = None
            self._current_jurisdiction = ""
            self._monitored_state = "unknown"

    def set_confirmed_mappings(self, mappings: dict[str, dict[str, str]]) -> None:
        self._confirmed_mappings = dict(mappings or {})

    def _clear_navigation_state(self) -> None:
        self._clear_preview_state()
        self._active_destination = None
        self._journey_active = False
        self._left_armistice_since_fuel = False
        self._map_session_open = False

    def _clear_preview_state(self) -> None:
        self._route_destination = None
        self._quantum_target = None
        self._quantum_target_seen = False
        self._quantum_raw_target = ""
        self._travel_preview_active = False
        self._map_preview_active = False
        self._preview_suppressed = False
        self._preview_suppressed_at = 0.0

    def parse_line(self, line: bytes | str) -> GameLocationDetection | None:
        """Compatibility API: return only confirmed locations."""
        update = self.parse_update(line)
        if update is None or not update.confirmed:
            return None
        return update.detection

    def parse_update(self, line: bytes | str) -> GameLocationUpdate | None:
        payload = line.encode("utf-8", errors="replace") if isinstance(line, str) else line
        if len(payload) > _MAX_LINE_BYTES:
            return None
        log_time = self._extract_log_time(payload)

        # High-confidence physical-environment fallbacks. These are used only
        # when Star Citizen confirms the active planetary grid/jurisdiction; route
        # calculation lines containing the same body identifiers are ignored.
        jurisdiction_match = _JURISDICTION_ENTER_RE.search(payload)
        if jurisdiction_match is not None:
            raw_jurisdiction = self._decode_token(jurisdiction_match.group(1))
            self._current_jurisdiction = {
                "hurston dynamics": "Hurston Dynamics",
                "arccorp": "ArcCorp",
                "microtech": "microTech",
                "crusader": "Crusader Industries",
                "crusader industries": "Crusader Industries",
                "uee": "UEE",
            }.get(raw_jurisdiction.casefold(), raw_jurisdiction)
            self._monitored_state = "monitored"
            # Jurisdiction is display context only. It is too broad to name the
            # player's precise physical location.
            return self._context_update()

        active_planet_match = _ACTIVE_PLANET_CELLS_RE.search(payload)
        if active_planet_match is not None:
            resolved = self._resolve(active_planet_match.group(2))
            update = self._confirm_environment(resolved)
            if update is not None:
                return update

        room_match = _STAMINA_ROOM_BODY_RE.search(payload)
        if room_match is not None:
            resolved = self._resolve(room_match.group(1))
            update = self._confirm_environment(resolved)
            if update is not None:
                return update

        inventory_transition = _INVENTORY_LOCATION_TRANSITION_RE.search(payload)
        if inventory_transition is not None:
            new_location = self._decode_token(inventory_transition.group(4))
            mapping = self._confirmed_mappings.get(new_location)
            if mapping is not None:
                mapped_name = str(mapping.get("name") or new_location)
                mapped_type = str(mapping.get("location_type") or "User confirmed location")
                if mapped_name.casefold() == "non monitored zone" or mapped_type.casefold() == "internal state":
                    self._current_jurisdiction = ""
                    self._monitored_state = "unmonitored"
                    return self._context_update()
                detection = GameLocationDetection(
                    name=mapped_name,
                    body=str(mapping.get("body") or ""),
                    raw_location=new_location,
                    location_type=mapped_type,
                    clock_mode="local" if str(mapping.get("clock_mode") or "utc") == "local" else "utc",
                    travel_state="location",
                )
                # A generic body transition must not overwrite a precise station
                # that streamed immediately before it on the same parent body.
                if (
                    self._last_confirmed is not None
                    and "station" in self._last_confirmed.location_type.casefold()
                    and detection.body.casefold() == self._last_confirmed.body.casefold()
                    and detection.name.casefold() == detection.body.casefold()
                ):
                    return self._context_update()
                return self._accept_physical_detection(detection)

        inventory_match = _LOCATION_INVENTORY_RE.search(payload)
        if inventory_match is not None:
            resolved = self._normalize_destination(self._resolve(inventory_match.group(1)))
            if not (is_precise_verse_location(resolved) or is_named_celestial_body(resolved)):
                return None
            detection = self._to_detection(resolved)
            # A low-orbit station can stream an exact station token immediately
            # before a broader city/planet inventory request on the same body.
            # Keep the station for a short window, but only while it is still the
            # current physical location. A real arrival at the city replaces it.
            station_hint = self._recent_current_station_hint(detection.body if detection else "")
            if (
                station_hint is not None
                and detection is not None
                and detection.name.casefold() != station_hint.resolved.name.casefold()
            ):
                return self._context_update()
            return self._accept_physical_detection(detection)

        selected_match = _QT_TARGET_SELECTED_RE.search(payload)
        if selected_match is not None:
            raw_token = self._decode_token(selected_match.group(1))
            resolved = self._normalize_destination(self._resolve(selected_match.group(1)))
            self._clear_recent_arrival_guard()
            if not self._allow_navigation_preview_event():
                self._record_diagnostic("starmap_selected_ignored_after_close", raw_token, resolved, log_time)
                return None
            self._record_diagnostic("starmap_selected", raw_token, resolved, log_time)
            current_route = self._route_destination
            if resolved is None and self._is_generic_reststop_token(raw_token):
                # The confirmation line may still carry only ObjectContainer_RestStop.
                # Keep the provisional/exact station already inferred from the fuel request.
                if current_route is None or not is_precise_verse_location(current_route.resolved):
                    self._route_destination = None
            elif resolved is None:
                self._route_destination = None
            elif is_precise_verse_location(resolved):
                self._route_destination = self._pending(
                    resolved, "navigation_selection", log_time
                )
            elif is_named_celestial_body(resolved):
                current = self._route_destination
                if not (
                    current is not None
                    and is_precise_verse_location(current.resolved)
                    and same_destination_body(current.resolved, resolved)
                ):
                    self._route_destination = self._pending(
                        resolved, "navigation_selection", log_time
                    )
            self._map_preview_active = (
                self._route_destination is not None and not self._preview_suppressed
            )
            return self._map_preview_update()

        projected_start_match = _QT_PROJECTED_START_RE.search(payload)
        if projected_start_match is not None and not self._journey_active:
            raw_start = self._decode_token(projected_start_match.group(1))
            resolved_start = resolve_verse_location(raw_start)
            self._record_diagnostic(
                "projected_route_start", raw_start, resolved_start, log_time
            )
            if is_precise_verse_location(resolved_start) or is_named_celestial_body(
                resolved_start
            ):
                physical = self._to_detection(resolved_start)
                if physical is not None:
                    # Route calculation is a high-quality snapshot of the current
                    # origin. Store it silently so Escape/F2 can restore it while
                    # the selected destination remains visible in the map.
                    self._set_physical_position(physical)

        for pattern, source in (
            (_QT_PROJECTED_DESTINATION_RE, "projected_route_destination"),
            (_QT_SURFACE_DESTINATION_RE, "surface_route_destination"),
            (_QT_SUCCESS_DESTINATION_RE, "calculated_route_destination"),
            (_QT_ROUTE_DESTINATION_RE, "calculated_route_destination"),
        ):
            route_match = pattern.search(payload)
            if route_match is None:
                continue
            raw_token = self._decode_token(route_match.group(1))
            resolved = self._normalize_destination(self._resolve(route_match.group(1)))
            if not self._allow_navigation_preview_event():
                self._record_diagnostic(f"{source}_ignored_after_close", raw_token, resolved, log_time)
                return None
            if resolved is None and source == "surface_route_destination":
                # The log has explicitly confirmed that the route ends on a
                # planetary surface, even when the target itself is an opaque
                # NavPoint/ObjectContainer identifier. Do not leave the old city
                # on screen: show No data, with a destination-body hint when one
                # was already observed elsewhere in the same route.
                resolved = unresolved_surface_destination(
                    raw_token, self._destination_body_hint()
                )
            self._record_diagnostic(source, raw_token, resolved, log_time)
            if resolved is not None and (
                is_precise_verse_location(resolved) or is_named_celestial_body(resolved)
            ):
                self._route_destination = self._pending(resolved, source, log_time)
                self._map_preview_active = not self._preview_suppressed
            return self._map_preview_update()

        station_stream_match = _STATION_STREAM_RE.search(payload)
        if station_stream_match is not None:
            station = self._station_from_internal_code(station_stream_match.group(1))
            if station is not None:
                # LocationManager_* is often emitted while the player's current
                # orbital station streams in. Keep it as a short-lived physical hint
                # and confirm it only when a matching body/jurisdiction follows.
                if b"locationmanager" in payload.lower():
                    self._station_hint = self._pending(station, "physical_station_hint", log_time)
                    # LocationManager_* is a strong physical station stream signal.
                    # Keep the station as the physical fallback even while the map
                    # is open; the preview stays visible until the map closes.
                    update = self._accept_physical_detection(self._to_detection(station))
                    if update is not None:
                        return update
                if self._is_generic_reststop_target():
                    self._route_destination = self._pending(
                        station, "streamed_station_destination", log_time
                    )
                    self._map_preview_active = not self._preview_suppressed
                    return self._map_preview_update()
            return None

        fuel_match = _QT_FUEL_TARGET_RE.search(payload)
        if fuel_match is not None:
            # A fuel request is emitted when the player clicks a Starmap target.
            # It is a destination preview signal, not proof that quantum travel has
            # started. Every new click must replace the previous destination; the
            # 1.0.5 code kept a stale active destination, which could lock the widget
            # on Deep Space for all later selections.
            raw_fuel_target = self._decode_token(fuel_match.group(1))
            resolved = self._normalize_destination(self._resolve(fuel_match.group(1)))
            if not self._allow_navigation_preview_event():
                self._record_diagnostic("starmap_fuel_ignored_after_close", raw_fuel_target, resolved, log_time)
                return None
            self._quantum_target_seen = True
            self._quantum_raw_target = raw_fuel_target
            previous_route = self._route_destination
            self._clear_recent_arrival_guard()

            # The four main orbital stations are often exposed initially only as
            # ObjectContainer_RestStop. When the physical body is known, use its
            # unique low-orbit station as a provisional preview. A later precise
            # station/route event always replaces this inference.
            if resolved is None and self._is_generic_reststop_token(raw_fuel_target):
                inferred_station = self._local_orbital_station_from_context()
                if inferred_station is not None:
                    self._route_destination = self._pending(
                        inferred_station, "inferred_local_orbital_station", log_time
                    )
                    previous_route = self._route_destination

            # Star Citizen often emits a precise public selection first, then a
            # generic ObjectContainer_RestStop or NavPoint_Dynamic fuel token.
            # That later opaque token is transport plumbing, not a new target.
            # Preserve the already-resolved Astro Atlas destination instead of
            # falling back to the previous physical city.
            preserve_previous_route = bool(
                previous_route is not None
                and is_precise_verse_location(previous_route.resolved)
                and (
                    resolved is None
                    or (
                        is_named_celestial_body(resolved)
                        and same_destination_body(previous_route.resolved, resolved)
                    )
                )
            )
            if not preserve_previous_route:
                self._route_destination = None
            self._record_diagnostic(
                "starmap_fuel_request", self._quantum_raw_target, resolved, log_time
            )
            self._quantum_target = (
                self._pending(resolved, "quantum_fuel", log_time) if resolved is not None else None
            )
            self._travel_preview_active = True
            self._release_preview_suppression_if_stale()
            self._map_preview_active = (
                (resolved is not None or self._route_destination is not None)
                and not self._preview_suppressed
            )
            self._left_armistice_since_fuel = False
            # A click in the Starmap is only a temporary preview. The destination
            # becomes locked only when the log confirms that the player exited a
            # monitored zone (actual free-space/QT transition).
            return self._map_preview_update_from_selected()

        if _EXITED_MONITORED_ZONE_RE.search(payload) is not None:
            # Internal context only: never replace the location label with
            # "Non monitored zone" and never infer a QT start from this signal.
            self._current_jurisdiction = ""
            self._monitored_state = "unmonitored"
            return self._context_update()

        if _ENTERED_MONITORED_ZONE_RE.search(payload) is not None:
            # This signal is deliberately too broad to name a planet, moon, site or
            # station. It only feeds the secondary display.
            self._monitored_state = "monitored"
            return self._context_update()

        if _QT_ARRIVED_RE.search(payload) is not None:
            detection = self._confirm_arrival(log_time, armistice_only=False)
            if detection is None:
                return None
            # Keep the selected final route across intermediate travel legs.
            # _confirm_arrival clears only the current leg and disables the preview.
            self._remember_recent_arrival(detection)
            self._set_physical_position(detection)
            return GameLocationUpdate(detection, True)

        if _ARMISTICE_LEFT_RE.search(payload) is not None and self._travel_preview_active:
            self._left_armistice_since_fuel = True
            return None

        if _ARMISTICE_ENTERED_RE.search(payload) is not None:
            # A route can be selected while the player is still near the origin.
            # Do not treat that origin armistice event as the destination.
            if self._travel_preview_active and not self._left_armistice_since_fuel:
                return None
            detection = self._confirm_arrival(log_time, armistice_only=True)
            if detection is None:
                return None
            self._remember_recent_arrival(detection)
            self._set_physical_position(detection)
            return GameLocationUpdate(detection, True)

        if _QT_CANNOT_INITIATE_RE.search(payload) is not None:
            if self._journey_active:
                return self._cancel_active_journey()
            if self._travel_preview_active:
                return None

        if _QT_NO_ROUTE_RE.search(payload) is not None:
            if self._journey_active:
                return self._cancel_active_journey()
            if self._travel_preview_active:
                return None
        return None

    def replay_completed(self) -> GameLocationDetection | None:
        """Discard historical navigation previews while preserving physical state."""
        latest = self._physical_position or self._last_confirmed
        self._clear_navigation_state()
        return latest

    def take_diagnostics(self) -> tuple[GameLocationDiagnostic, ...]:
        if not self._diagnostics:
            return ()
        items = tuple(self._diagnostics)
        self._diagnostics.clear()
        return items

    def _record_diagnostic(
        self,
        event: str,
        raw_token: str,
        resolved: ResolvedVerseLocation | None,
        log_time: datetime | None,
    ) -> None:
        if resolved is None:
            confidence = "unresolved"
            name = ""
            body = ""
        elif is_precise_verse_location(resolved):
            confidence = "exact"
            name = resolved.name
            body = resolved.body
        elif is_named_celestial_body(resolved):
            confidence = "parent_body"
            name = resolved.name
            body = resolved.body
        else:
            confidence = "generic"
            name = resolved.name
            body = resolved.body
        self._diagnostics.append(
            GameLocationDiagnostic(
                str(event),
                str(raw_token),
                str(name),
                str(body),
                confidence,
                log_time.isoformat() if log_time is not None else "",
            )
        )

    @property
    def current_jurisdiction(self) -> str:
        return self._current_jurisdiction

    @property
    def monitored_state(self) -> str:
        return self._monitored_state

    def _release_preview_suppression_if_stale(self) -> None:
        if not self._preview_suppressed:
            return
        if self._map_session_open or (
            time.monotonic() - self._preview_suppressed_at >= _MAP_CLOSE_SUPPRESSION_SECONDS
        ):
            self._preview_suppressed = False
            self._preview_suppressed_at = 0.0

    def _allow_navigation_preview_event(self) -> bool:
        """Ignore delayed route lines after close, unless a new F2 session opened."""
        if not self._preview_suppressed:
            self._map_session_open = True
            return True
        self._release_preview_suppression_if_stale()
        if self._preview_suppressed:
            return False
        self._map_session_open = True
        return True

    def _visible_detection(self) -> GameLocationDetection | None:
        if self._journey_active and self._active_destination is not None:
            return self._to_detection(
                self._active_destination, travel_state="quantum_destination"
            )
        if self._map_preview_active and not self._preview_suppressed:
            preview = self._map_preview_update_from_selected() or self._map_preview_update()
            if preview is not None:
                return preview.detection
        return self._physical_position or self._last_confirmed

    def _context_update(self) -> GameLocationUpdate | None:
        detection = self._visible_detection()
        return GameLocationUpdate(detection, False) if detection is not None else None

    def _cancel_active_journey(self) -> GameLocationUpdate:
        self._clear_navigation_state()
        self._current_jurisdiction = ""
        self._monitored_state = "unmonitored"
        detection = self._space_detection("Deep Space")
        self._set_physical_position(detection)
        return GameLocationUpdate(detection, True)

    def _confirm_environment(
        self, resolved: ResolvedVerseLocation | None
    ) -> GameLocationUpdate | None:
        if not is_named_celestial_body(resolved):
            return None

        hint = self._station_hint
        if (
            hint is not None
            and self._is_fresh(hint, None)
            and same_destination_body(hint.resolved, resolved)
        ):
            self._station_hint = None
            return self._accept_physical_detection(self._to_detection(hint.resolved))

        # Do not downgrade a precise orbital station to its generic parent body
        # when the next lines only repeat the planetary environment.
        if (
            self._physical_position is not None
            and "station" in self._physical_position.location_type.casefold()
            and self._physical_position.body.casefold() == resolved.body.casefold()
        ):
            return self._context_update()

        detection = self._to_detection(resolved)
        if detection is None:
            return None
        return self._accept_physical_detection(detection)

    def _accept_physical_detection(
        self, detection: GameLocationDetection | None
    ) -> GameLocationUpdate | None:
        if detection is None:
            return None
        if self._should_preserve_recent_arrival(detection):
            return self._context_update()
        # During a confirmed QT leg, the destination remains locked on screen
        # until arrival. Physical origin messages must not overwrite it.
        if self._journey_active:
            return None
        self._set_physical_position(detection)
        # While the map is open, keep the last clicked destination visible but
        # refresh the physical position silently in the background. Escape/F2
        # will then restore this freshly confirmed position immediately.
        if self._map_preview_active and not self._preview_suppressed:
            return None
        return GameLocationUpdate(detection, True)

    def _map_preview_update(self) -> GameLocationUpdate | None:
        if self._preview_suppressed or not self._map_preview_active or self._route_destination is None:
            return None
        detection = self._to_detection(
            self._route_destination.resolved, travel_state="map_preview"
        )
        return GameLocationUpdate(detection, False)

    def _map_preview_update_from_selected(self) -> GameLocationUpdate | None:
        if self._preview_suppressed or not self._map_preview_active:
            return None
        resolved = self._best_quantum_destination()
        if resolved is None:
            return None
        detection = self._to_detection(resolved, travel_state="map_preview")
        return GameLocationUpdate(detection, False)

    @property
    def map_preview_active(self) -> bool:
        return bool(self._map_preview_active and not self._preview_suppressed)

    @property
    def map_session_open(self) -> bool:
        return bool(self._map_session_open)

    def begin_map_session(self) -> None:
        """Explicit F2 opening: allow a new preview and discard stale map clicks."""
        self._map_session_open = True
        self._preview_suppressed = False
        self._preview_suppressed_at = 0.0
        if not self._journey_active:
            self._route_destination = None
            self._quantum_target = None
            self._quantum_target_seen = False
            self._quantum_raw_target = ""
            self._travel_preview_active = False
            self._map_preview_active = False

    def restore_after_map_close(self) -> GameLocationUpdate | None:
        """End a Starmap preview and restore the separate physical snapshot."""
        if not self._map_preview_active and not self._map_session_open:
            return None
        return self.force_current_position()

    def force_current_position(self) -> GameLocationUpdate | None:
        """Escape/F2: show physical state, never the selected Starmap destination."""
        self._map_session_open = False
        self._map_preview_active = False
        self._travel_preview_active = False
        self._preview_suppressed = True
        self._preview_suppressed_at = time.monotonic()
        if self._journey_active and self._active_destination is not None:
            detection = self._to_detection(
                self._active_destination, travel_state="quantum_destination"
            )
            return GameLocationUpdate(detection, False)
        if self._physical_position is not None:
            return GameLocationUpdate(self._physical_position, False)
        return None

    def commit_quantum_destination(self) -> GameLocationUpdate | None:
        """Commit the current route when the player holds the QT activation key.

        Some 4.9 sessions do not write a dedicated quantum-start line when the
        player is already in unmonitored space. The ordinary Windows B-key probe
        supplies that missing transition without reading or modifying game memory.
        """
        destination = self._best_quantum_destination()
        if destination is None:
            return None
        self._active_destination = destination
        self._journey_active = True
        # Once QT is engaged, keep the destination visible. Monitored-space and
        # jurisdiction events update only the secondary display.
        self._map_preview_active = False
        self._preview_suppressed = False
        self._preview_suppressed_at = 0.0
        detection = self._to_detection(destination, travel_state="quantum_destination")
        return GameLocationUpdate(detection, False)

    def _preview_update_if_active(self, *, force_space: bool = False) -> GameLocationUpdate | None:
        if not self._travel_preview_active:
            return None
        resolved = self._best_quantum_destination()
        if resolved is None:
            if not force_space:
                return None
            return GameLocationUpdate(self._space_detection("Deep space"), False)
        detection = self._to_detection(resolved, travel_state="quantum_destination")
        return GameLocationUpdate(detection, False)

    def _best_quantum_destination(self) -> ResolvedVerseLocation | None:
        target = self._quantum_target.resolved if self._quantum_target is not None else None
        route = self._route_destination.resolved if self._route_destination is not None else None

        if is_precise_verse_location(target):
            return target
        station = self._station_for_generic(target)
        if station is not None:
            return station
        if target is not None and is_named_celestial_body(target):
            if route is not None and is_precise_verse_location(route) and same_destination_body(route, target):
                return route
            return target
        if route is not None and (
            is_precise_verse_location(route) or is_named_celestial_body(route)
        ):
            return route
        return None

    def _confirm_arrival(
        self,
        confirmation_time: datetime | None,
        *,
        armistice_only: bool,
    ) -> GameLocationDetection | None:
        active_destination = self._active_destination
        target = self._quantum_target
        route = self._route_destination
        target_was_seen = self._quantum_target_seen
        raw_target = self._quantum_raw_target
        self._clear_navigation_state()

        if active_destination is not None:
            return self._to_detection(active_destination)

        if target is not None and self._is_fresh(target, confirmation_time):
            if armistice_only and target.source != "quantum_fuel":
                return None
            if is_precise_verse_location(target.resolved):
                return self._to_detection(target.resolved)

            if (
                route is not None
                and self._is_fresh(route, confirmation_time)
                and is_precise_verse_location(route.resolved)
                and same_destination_body(route.resolved, target.resolved)
            ):
                return self._to_detection(route.resolved)

            station = self._station_for_generic(target.resolved)
            if station is not None:
                return self._to_detection(station)
            if is_named_celestial_body(target.resolved):
                return self._to_detection(target.resolved)
            return None

        if route is not None and self._is_fresh(route, confirmation_time):
            opaque_target_matches_route = self._tokens_equivalent(
                raw_target, route.resolved.raw_name
            )
            generic_station_target = self._is_generic_reststop_token(raw_target)
            calculated_final_destination = route.source in {
                "projected_route_destination",
                "surface_route_destination",
                "calculated_route_destination",
                "streamed_station_destination",
            }
            if target_was_seen and (
                opaque_target_matches_route
                or generic_station_target
                or calculated_final_destination
            ):
                if is_precise_verse_location(route.resolved):
                    return self._to_detection(route.resolved)

            if (
                not armistice_only
                and not target_was_seen
                and (
                    is_precise_verse_location(route.resolved)
                    or is_named_celestial_body(route.resolved)
                )
            ):
                return self._to_detection(route.resolved)
        return None

    def _space_detection(self, label: str) -> GameLocationDetection:
        body = self._physical_position.body if self._physical_position is not None else ""
        return GameLocationDetection(
            name=label,
            body=body,
            raw_location="SPACE",
            location_type="Space",
            clock_mode="utc",
            travel_state="space",
        )

    def _non_monitored_detection(self) -> GameLocationDetection:
        return GameLocationDetection(
            name="Non monitored zone",
            body="",
            raw_location="NON_MONITORED_ZONE",
            location_type="Space",
            clock_mode="utc",
            travel_state="non_monitored",
        )

    def _is_generic_reststop_target(self) -> bool:
        return self._is_generic_reststop_token(self._quantum_raw_target)

    @staticmethod
    def _is_generic_reststop_token(raw_token: str) -> bool:
        compact = re.sub(r"[^a-z0-9]+", "", str(raw_token or "").casefold())
        return "reststop" in compact

    @staticmethod
    def _tokens_equivalent(left: str, right: str) -> bool:
        compact = lambda value: re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
        a, b = compact(left), compact(right)
        return bool(a and b and a == b)

    @staticmethod
    def _decode_token(raw_value: bytes) -> str:
        return raw_value.decode("utf-8", errors="replace").strip().strip('"\'')

    @classmethod
    def _station_from_internal_code(cls, raw_value: bytes) -> ResolvedVerseLocation | None:
        code = cls._decode_token(raw_value).upper()
        leo_match = re.fullmatch(r"(ARC|CRU|HUR|MIC)-LEO\d*", code)
        if leo_match is not None:
            return resolve_verse_location(f"RR_{leo_match.group(1)}_LEO")
        body = resolve_verse_location(code)
        if body is None:
            return None
        return nearest_named_station(body.body)

    @staticmethod
    def _station_for_generic(
        resolved: ResolvedVerseLocation | None,
    ) -> ResolvedVerseLocation | None:
        if resolved is None or resolved.exact_location:
            return None
        body_token = str(resolved.body or "").upper()
        if not (
            re.match(r"^(?:ARC|CRU|HUR|MIC)-L\d", body_token)
            or re.match(r"^PYR\d", body_token)
        ):
            return None
        return nearest_named_station(resolved.body)


    @classmethod
    def _normalize_destination(
        cls, resolved: ResolvedVerseLocation | None
    ) -> ResolvedVerseLocation | None:
        """Promote generic Lagrange/LEO bodies to their public station record."""
        station = cls._station_for_generic(resolved)
        return station or resolved

    def _clear_recent_arrival_guard(self) -> None:
        self._recent_arrival = None
        self._recent_arrival_at = 0.0

    def _remember_recent_arrival(self, detection: GameLocationDetection) -> None:
        self._recent_arrival = detection
        self._recent_arrival_at = time.monotonic()

    def _should_preserve_recent_arrival(self, incoming: GameLocationDetection) -> bool:
        recent = self._recent_arrival
        if recent is None:
            return False
        if time.monotonic() - self._recent_arrival_at > _RECENT_ARRIVAL_GUARD_SECONDS:
            self._clear_recent_arrival_guard()
            return False
        if recent.name.casefold() == incoming.name.casefold():
            return False
        if not recent.body or recent.body.casefold() != incoming.body.casefold():
            return False

        recent_type = recent.location_type.casefold().replace("_", " ").strip()
        incoming_type = incoming.location_type.casefold().replace("_", " ").strip()
        precise_recent = recent_type not in {"", "body", "landing zone", "space"}
        broad_incoming = (
            incoming.name.casefold() == incoming.body.casefold()
            or incoming_type in {"body", "landing zone"}
        )
        return precise_recent and broad_incoming

    def _set_physical_position(self, detection: GameLocationDetection) -> None:
        self._physical_position = detection
        # Keep the historical attribute synchronized for compatibility with old
        # recovery code and tests; it is no longer used as the map-close source.
        self._last_confirmed = detection

    def _local_orbital_station_from_context(self) -> ResolvedVerseLocation | None:
        # Prefer a destination-side planet already seen in the route. This allows,
        # for example, Seraphim to be previewed from Hurston once Crusader has
        # appeared in the route context. Fall back to the current physical body
        # only when the log has supplied no destination-side body yet.
        candidates: list[str] = []
        for pending in (self._route_destination, self._quantum_target):
            if pending is not None and pending.resolved.body:
                candidates.append(str(pending.resolved.body))

        physical = self._physical_position
        if physical is not None:
            physical_type = physical.location_type.casefold().replace("_", " ").strip()
            if physical_type not in {"space", "space station"} and "station" not in physical_type:
                candidates.append(str(physical.body))

        for body_name in candidates:
            station_name = _LOCAL_ORBITAL_STATIONS.get(body_name.casefold())
            if station_name:
                return resolve_verse_location(station_name)
        return None

    def _destination_body_hint(self) -> str:
        """Return only a body already observed on the destination side of a route."""
        for pending in (self._quantum_target, self._route_destination):
            if pending is not None and str(pending.resolved.body or "").strip():
                return str(pending.resolved.body).strip()
        if self._active_destination is not None:
            return str(self._active_destination.body or "").strip()
        return ""

    def _recent_current_station_hint(self, body_name: str) -> _PendingDestination | None:
        hint = self._station_hint
        current = self._physical_position
        if hint is None or current is None:
            return None
        if time.monotonic() - hint.observed_at > _STATION_HINT_MAX_AGE_SECONDS:
            return None
        if current.name.casefold() != hint.resolved.name.casefold():
            return None
        if str(body_name or "").casefold() != hint.resolved.body.casefold():
            return None
        return hint

    @staticmethod
    def _pending(
        resolved: ResolvedVerseLocation,
        source: str,
        log_time: datetime | None,
    ) -> _PendingDestination:
        return _PendingDestination(resolved, source, log_time, time.monotonic())

    @staticmethod
    def _is_fresh(pending: _PendingDestination, confirmation_time: datetime | None) -> bool:
        if pending.log_time is not None and confirmation_time is not None:
            elapsed = (confirmation_time - pending.log_time).total_seconds()
            return 0 <= elapsed <= _PENDING_MAX_AGE_SECONDS
        return (time.monotonic() - pending.observed_at) <= _PENDING_MAX_AGE_SECONDS

    @staticmethod
    def _extract_log_time(payload: bytes) -> datetime | None:
        match = _TIMESTAMP_RE.search(payload)
        if match is None:
            return None
        try:
            text = match.group(1).decode("ascii").replace("Z", "+00:00")
            return datetime.fromisoformat(text).astimezone(timezone.utc)
        except (UnicodeDecodeError, ValueError):
            return None

    @classmethod
    def _resolve(cls, raw_value: bytes) -> ResolvedVerseLocation | None:
        return resolve_verse_location(cls._decode_token(raw_value))

    @staticmethod
    def _to_detection(
        resolved: ResolvedVerseLocation | None,
        *,
        travel_state: str = "location",
    ) -> GameLocationDetection | None:
        if resolved is None:
            return None
        return GameLocationDetection(
            name=resolved.name,
            body=resolved.body,
            raw_location=resolved.raw_name,
            location_type=resolved.location_type,
            clock_mode="utc" if location_uses_utc_clock(resolved) else "local",
            travel_state=travel_state,
        )


class GameLogLocationMonitor(QObject):
    """Read-only, incremental Game.log monitor driven by a Qt timer."""

    location_changed = Signal(str, str, str)
    vehicle_changed = Signal(str, str)
    status_changed = Signal(str)

    def __init__(self, settings: QSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._public_parser_directory = public_parser_directory()
        self.recorder = PublicParserRecorder(root=self._public_parser_directory)
        self.parser = GameLogLocationParser(self.recorder.load_confirmed_mappings())
        self.vehicle_parser = VehicleContextParser()
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll)
        self._file: BinaryIO | None = None
        self._path: Path | None = None
        self._position = 0
        self._partial = b""
        self._last_identity: tuple[int, int] | None = None
        self._last_location_key = ""
        self._last_vehicle_key = ""
        self._missing_polls = 0
        self._last_status = ""
        self.settings.remove("game_log/diagnostic_path")
        self.settings.remove("game_log/location_test_directory")
        self.settings.setValue("game_log/public_parser_file", str(public_parser_output_path()))

    @property
    def active_path(self) -> Path | None:
        return self._path

    @property
    def enabled(self) -> bool:
        return self.settings.value("game_log/auto_location_enabled", True, type=bool)

    def start(self) -> None:
        if not self.enabled:
            self._set_status("Détection Game.log désactivée")
            return
        if not self.timer.isActive():
            self.timer.start()
        self._locate_and_open()

    def stop(self) -> None:
        self.timer.stop()
        self._close_file()

    def shutdown(self) -> None:
        self.stop()
        self.recorder.close_session()

    def reconfigure(self) -> None:
        """Apply settings without replaying an old location from the same file."""
        self.settings.remove("game_log/location_test_recording_enabled")
        if not self.enabled:
            self.stop()
            self._set_status("Détection Game.log désactivée")
            return

        selected = self._select_existing_path(self.candidate_paths())
        if selected is not None and self._file is not None and self._path == selected:
            if not self.timer.isActive():
                self.timer.start()
            self._set_status(f"Game.log surveillé · {selected.parent.name}")
            return

        self.stop()
        self._last_location_key = ""
        self.start()

    def poll(self) -> None:
        if not self.enabled:
            self.stop()
            self._set_status("Détection Game.log désactivée")
            return
        if self._file is None or self._path is None:
            self._missing_polls += 1
            if self._missing_polls == 1 or self._missing_polls % 12 == 0:
                self._locate_and_open()
            return

        try:
            stat = self._path.stat()
        except OSError:
            self._set_status("Game.log momentanément indisponible")
            self._close_file()
            return

        identity = (int(getattr(stat, "st_dev", 0)), int(getattr(stat, "st_ino", 0)))
        if stat.st_size < self._position or (
            self._last_identity is not None and identity != self._last_identity
        ):
            # New game session or log replacement: reopen and recover the latest
            # location from the new file only.
            self._open_path(self._path)
            return

        self._last_identity = identity
        try:
            self._file.seek(self._position)
            chunk = self._file.read(_MAX_READ_BYTES)
        except OSError:
            self._set_status("Lecture Game.log interrompue")
            self._close_file()
            return
        if not chunk:
            return
        self._position += len(chunk)
        self._consume(chunk, emit_latest_only=False)

    def _locate_and_open(self) -> None:
        selected = self._select_existing_path(self.candidate_paths())
        if selected is None:
            self._set_status("Game.log introuvable · choisir le fichier dans Réglage")
            self._close_file()
            return
        self._open_path(selected)

    def _open_path(self, path: Path) -> None:
        self._close_file()
        try:
            handle = path.open("rb")
            stat = path.stat()
        except OSError:
            self._set_status("Impossible d’ouvrir Game.log en lecture seule")
            return

        self._file = handle
        self._path = path
        self.recorder.start_session(path)
        self._last_identity = (int(getattr(stat, "st_dev", 0)), int(getattr(stat, "st_ino", 0)))
        self._partial = b""
        start = max(0, stat.st_size - _MAX_RECOVERY_BYTES)
        try:
            handle.seek(start)
            recovery = handle.read(stat.st_size - start)
        except OSError:
            self._set_status("Impossible de lire la fin de Game.log")
            self._close_file()
            return
        if start > 0:
            separator = recovery.find(b"\n")
            recovery = recovery[separator + 1 :] if separator >= 0 else b""
        self._position = stat.st_size
        self._missing_polls = 0
        self.settings.setValue("game_log/active_path", str(path))
        self.settings.sync()
        self._set_status(f"Game.log surveillé · {path.parent.name}")
        # A replaced Game.log starts a new game session. Do not carry a ship
        # palette from the previous session when no active vehicle has been seen.
        self._last_vehicle_key = ""
        self._emit_vehicle(VehicleContextUpdate("", ""))
        self._consume(recovery, emit_latest_only=True)

    def _consume(self, chunk: bytes, *, emit_latest_only: bool) -> None:
        data = self._partial + chunk
        lines = data.splitlines(keepends=True)
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            self._partial = lines.pop()
            if len(self._partial) > _MAX_LINE_BYTES:
                self._partial = b""
        else:
            self._partial = b""

        updates: list[GameLocationUpdate] = []
        vehicle_updates: list[VehicleContextUpdate] = []
        for line in lines:
            vehicle_update = self.vehicle_parser.parse_line(line)
            if vehicle_update is not None:
                vehicle_updates.append(vehicle_update)
            update = self.parser.parse_update(line)
            self.parser.take_diagnostics()
            self.recorder.observe_line(line)
            if update is not None:
                updates.append(update)
        if emit_latest_only:
            # Recovery/replay rebuilds only the last confirmed physical state. Old
            # Starmap previews must never become the startup location.
            latest_confirmed = self.parser.replay_completed()
            if latest_confirmed is not None:
                self._emit(latest_confirmed)
            if vehicle_updates:
                self._emit_vehicle(vehicle_updates[-1])
            return
        for vehicle_update in vehicle_updates:
            self._emit_vehicle(vehicle_update)
        for update in updates:
            self._emit(update.detection)

    def _emit_vehicle(self, update: VehicleContextUpdate) -> None:
        key = f"{update.manufacturer_id}|{update.vehicle_code}".casefold()
        if key == self._last_vehicle_key:
            return
        self._last_vehicle_key = key
        self.vehicle_changed.emit(update.manufacturer_id, update.vehicle_code)

    def _emit(self, detection: GameLocationDetection) -> None:
        jurisdiction = self.parser.current_jurisdiction
        monitored_state = self.parser.monitored_state
        key = (
            f"{detection.name.casefold()}|{detection.body.casefold()}|"
            f"{detection.clock_mode}|{detection.travel_state}|"
            f"{jurisdiction.casefold()}|{monitored_state}"
        )
        if key == self._last_location_key:
            return
        self._last_location_key = key
        self.settings.setValue("game_log/last_location", detection.name)
        self.settings.setValue("game_log/last_body", detection.body)
        self.settings.setValue("game_log/last_raw_location", detection.raw_location)
        self.settings.setValue("game_log/location_type", detection.location_type)
        self.settings.setValue("game_log/clock_mode", detection.clock_mode)
        self.settings.setValue("game_log/travel_state", detection.travel_state)
        self.settings.setValue("game_log/jurisdiction", jurisdiction)
        self.settings.setValue("game_log/monitored_state", monitored_state)
        self.settings.sync()
        self.recorder.observe_display(detection.name, detection.body, detection.travel_state)
        if detection.travel_state == "map_preview":
            status = f"Prévisualisation : {detection.name}"
        elif detection.travel_state == "quantum_destination":
            status = f"Destination : {detection.name}"
        elif detection.travel_state == "non_monitored":
            status = "Contexte non surveillé"
        elif detection.travel_state == "space":
            status = "Deep space"
        elif detection.clock_mode == "utc":
            status = f"Lieu détecté : {detection.name}"
        else:
            status = f"Lieu détecté : {detection.name} · {detection.body}"
        self._set_status(status)
        self.location_changed.emit(detection.name, detection.body, detection.raw_location)

    @property
    def map_preview_active(self) -> bool:
        return self.parser.map_preview_active

    @property
    def map_session_open(self) -> bool:
        return self.parser.map_session_open

    def begin_map_session(self) -> None:
        self.parser.begin_map_session()

    def restore_after_map_close(self) -> None:
        update = self.parser.restore_after_map_close()
        if update is not None:
            self._last_location_key = ""
            self._emit(update.detection)

    def force_current_position(self) -> None:
        update = self.parser.force_current_position()
        if update is not None:
            # Force a refresh even when the same physical location was already
            # emitted before the player opened the mobiGlas.
            self._last_location_key = ""
            self._emit(update.detection)

    def commit_quantum_destination(self) -> None:
        update = self.parser.commit_quantum_destination()
        if update is not None:
            self._last_location_key = ""
            self._emit(update.detection)

    @property
    def public_parser_output_file(self) -> Path:
        return self.recorder.output_path

    def confirm_test_location(self, label: str) -> dict[str, object]:
        """Save the manual label with the most probable recent Game.log code."""
        result = self.recorder.confirm_location(label)
        if bool(result.get("saved")):
            code = str(result.get("location_code") or "")
            self._set_status(f"Capture Public Real Time Checker enregistrée · {code}")
        elif str(result.get("reason") or "") == "no_recent_location_code":
            self._set_status("Capture impossible · aucun code de localisation récent")
        else:
            self._set_status("Capture Public Real Time Checker non enregistrée")
        return result

    def _close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = None
        self._path = None
        self._position = 0
        self._partial = b""
        self._last_identity = None
        self.recorder.close_session()
        self.parser.reset(clear_confirmed=True)

    def _set_status(self, status: str) -> None:
        if status == self._last_status:
            return
        self._last_status = status
        self.settings.setValue("game_log/status", status)
        self.settings.sync()
        self.status_changed.emit(status)

    def candidate_paths(self) -> tuple[Path, ...]:
        candidates: list[Path] = []
        configured = self.settings.value("game_log/path", "", type=str).strip()
        if configured:
            path = Path(configured).expanduser()
            if path.is_dir():
                path = path / "Game.log"
            candidates.append(path)

        environment_path = os.environ.get("SC_GAME_LOG", "").strip()
        if environment_path:
            candidates.append(Path(environment_path).expanduser())

        active = self.settings.value("game_log/active_path", "", type=str).strip()
        if active:
            candidates.append(Path(active).expanduser())

        if os.name == "nt":
            drives = [Path(f"{letter}:\\") for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ"]
            roots = (
                Path("Program Files") / "Roberts Space Industries" / "StarCitizen",
                Path("Program Files (x86)") / "Roberts Space Industries" / "StarCitizen",
                Path("Roberts Space Industries") / "StarCitizen",
                Path("RSI") / "StarCitizen",
                Path("Games") / "Roberts Space Industries" / "StarCitizen",
                Path("Games") / "StarCitizen",
                Path("StarCitizen"),
            )
            for drive in drives:
                if not drive.exists():
                    continue
                for root in roots:
                    for channel in _CHANNELS:
                        candidates.append(drive / root / channel / "Game.log")

        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = os.path.normcase(os.path.abspath(str(candidate)))
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return tuple(unique)

    @staticmethod
    def _select_existing_path(paths: Iterable[Path]) -> Path | None:
        existing: list[tuple[int, Path]] = []
        for path in paths:
            try:
                if path.is_file():
                    existing.append((path.stat().st_mtime_ns, path))
            except OSError:
                continue
        if not existing:
            return None
        existing.sort(key=lambda item: item[0], reverse=True)
        return existing[0][1]
