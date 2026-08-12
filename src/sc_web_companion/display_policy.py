from __future__ import annotations


def context_label(jurisdiction: str, monitored_state: str) -> str:
    """Compatibility helper: monitored/jurisdiction context is no longer displayed."""
    del jurisdiction, monitored_state
    return ""


def secondary_display(
    *,
    location_name: str,
    weather: str,
    travel_state: str,
    jurisdiction: str,
    monitored_state: str,
    unknown_site: bool,
    station: bool,
    exact_site: bool,
) -> str:
    """Return the widget's second information line.

    The line is reserved for planetary weather. Stations, deep space, unknown
    sites and monitored-space context intentionally leave it empty.
    """
    del location_name, jurisdiction, monitored_state, exact_site
    weather_text = str(weather or "").strip().upper()
    travel = str(travel_state or "location").strip().casefold()

    # The secondary line describes the weather of the player's current
    # planetary location only. A Starmap preview or an active quantum
    # destination is not the player's current surface weather.
    if travel != "location" or unknown_site or station:
        return ""
    return weather_text
