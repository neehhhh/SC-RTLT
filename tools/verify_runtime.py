from __future__ import annotations

from importlib.resources import files
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# QtMultimedia can write an informational FFmpeg banner to stderr even when
# validation succeeds. Keep the installer log focused on actual failures.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false")

import PySide6
from PySide6.QtCore import QObject, QSettings, QTimer, Signal  # noqa: F401
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: F401
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings  # noqa: F401
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
from PySide6.QtWidgets import QApplication

import sc_web_companion
from sc_web_companion.display_policy import secondary_display
from sc_web_companion.game_log_location import GameLogLocationParser
from sc_web_companion.game_ui_state import GameUiLogParser, should_hide_widget_for_game_ui
from sc_web_companion.language import current_language, tr, translate_location_name, translate_weather
from sc_web_companion.public_parser_recorder import PublicParserRecorder
from sc_web_companion.verse_time import (
    astro_atlas_location_count,
    is_co_rotating_orbital_location,
    location_clock_model,
    location_uses_utc_clock,
    resolve_verse_location,
)

expected_version = sys.argv[1] if len(sys.argv) > 1 else ""
if not expected_version or sc_web_companion.__version__ != expected_version:
    raise RuntimeError(
        f"Version installée incorrecte : {sc_web_companion.__version__!r}, "
        f"attendu {expected_version!r}."
    )

package_root = files("sc_web_companion")
for resource_name in (
    "assets/app_icon.svg",
    "assets/app_icon.png",
    "assets/app_icon.ico",
    "assets/versetime/bodies.csv",
    "assets/versetime/locations.csv",
    "assets/location_mappings.json",
    "assets/astro_atlas_index.json",
    "public_parser_recorder.py",
):
    if not package_root.joinpath(resource_name).is_file():
        raise FileNotFoundError(f"Ressource absente : {resource_name}")

if not GameUiLogParser().parse_line("<PlayerInventoryRequest>").active:
    raise RuntimeError("Le détecteur d'inventaire installé ne peut pas être initialisé.")
if (
    not should_hide_widget_for_game_ui(True, "inventory")
    or should_hide_widget_for_game_ui(False, "inventory")
):
    raise RuntimeError("L'inventaire doit masquer complètement le widget et le restaurer à sa fermeture.")

if astro_atlas_location_count() != 516:
    raise RuntimeError("Le référentiel Astro Atlas installé est incomplet.")
for station_name in ("Baijini Point", "Everus Harbor", "Port Tressler", "Seraphim Station"):
    station = resolve_verse_location(station_name)
    if not is_co_rotating_orbital_location(station) or location_clock_model(station) != "co_rotating_orbit":
        raise RuntimeError(f"Modèle orbital synchronisé invalide : {station_name}")
for station_name in ("Covalex Shipping Hub Gundo", "Security Post Kareah", "Ruin Station"):
    if location_clock_model(resolve_verse_location(station_name)) != "reference":
        raise RuntimeError(f"Fausse heure locale attribuée à {station_name}.")

# VerseTime and unknown-site policy.
ludlow = resolve_verse_location("ab_collector_gas_Stanton1")
if ludlow is None or (ludlow.name, ludlow.body) != ("Ludlow", "Hurston"):
    raise RuntimeError("Ludlow n'est pas résolu depuis VerseTime.")
unknown = resolve_verse_location("hurdyn_cluster_unknown_surface_site")
if (
    unknown is None
    or unknown.name != "No data available"
    or unknown.location_type != "Unknown site"
    or not location_uses_utc_clock(unknown)
):
    raise RuntimeError("Un site inconnu doit rester No data available en UTC.")
shubin = resolve_verse_location("Stanton4a_Shubin_SMCa_8")
if shubin is None or shubin.name != "Shubin Mining Facility SMCa-8" or location_uses_utc_clock(shubin):
    raise RuntimeError("La résolution VerseTime exacte de Shubin SMCa-8 est indisponible.")

mapping_payload = json.loads(
    package_root.joinpath("assets/location_mappings.json").read_text(encoding="utf-8")
)
mappings = {str(item["raw_token"]): item for item in mapping_payload.get("mappings", [])}
parser = GameLogLocationParser(mappings)

# Numeric locations and monitored context.
calliope = parser.parse_update(
    "<Update Inventory Location> Player [ValidationOnly] is changing location. "
    "Landing [0] -> [0]. Location [1902223495] -> [4167598756]"
)
if calliope is None or calliope.detection.name != "Atmosphère de Calliope":
    raise RuntimeError("La correspondance Calliope n'est pas chargée.")
new_babbage = parser.parse_update(
    "<Update Inventory Location> Player [ValidationOnly] is changing location. "
    "Landing [0] -> [0]. Location [4167598756] -> [3170699229]"
)
if new_babbage is None or (new_babbage.detection.name, new_babbage.detection.body) != ("New Babbage", "microTech"):
    raise RuntimeError("L'identifiant numérique de New Babbage n'est pas chargé.")
physical_before_context = new_babbage.detection.name
internal = parser.parse_update(
    "<Update Inventory Location> Player [ValidationOnly] is changing location. "
    "Landing [0] -> [0]. Location [4167598756] -> [1902223495]"
)
if (
    internal is None
    or internal.detection.name != physical_before_context
    or internal.detection.name == "Non monitored zone"
    or parser.monitored_state != "unmonitored"
):
    raise RuntimeError("Non monitored doit rester un contexte interne sans renommer le lieu.")
entered = parser.parse_update('Added notification "Entered Monitored Space: "')
if (
    entered is None
    or entered.detection.name != physical_before_context
    or parser.monitored_state != "monitored"
):
    raise RuntimeError("Entered Monitored Space doit conserver le dernier lieu physique.")

# Station precision and parent-body protection.
station_parser = GameLogLocationParser(mappings)
everus = station_parser.parse_update(
    "LocationManager [LocationManager_HUR-LEO1]: Shopping provider pointer null"
)
if everus is None or everus.detection.name != "Everus Harbor":
    raise RuntimeError("Everus Harbor n'est pas détecté par LocationManager_HUR-LEO1.")
not_downgraded = station_parser.parse_update(
    "[STAMINA] -> RoomName: OOC_Stanton_1_Hurston"
)
if not_downgraded is None or not_downgraded.detection.name != "Everus Harbor":
    raise RuntimeError("Une station précise est remplacée par son corps parent.")

seraphim_parser = GameLogLocationParser(mappings)
seraphim = seraphim_parser.parse_update(
    "LocationManager_rs_ext_CRU-LEO1 streamed physical location"
)
if seraphim is None or seraphim.detection.name != "Seraphim Station":
    raise RuntimeError("Seraphim Station n'est pas détectée.")
seraphim_inventory = seraphim_parser.parse_update(
    "<RequestLocationInventory> Player[ValidationOnly] requested inventory for Location[Stanton2_Orison]"
)
if seraphim_inventory is None or seraphim_inventory.detection.name != "Seraphim Station":
    raise RuntimeError("Seraphim Station est écrasée par un inventaire Orison/Crusader.")

# A generic RestStop click must preview the unique low-orbit station of the
# current major planet before the precise confirmation line arrives.
for physical_token, expected_station in (
    ("Stanton1_Lorville", "Everus Harbor"),
    ("Stanton2_Orison", "Seraphim Station"),
    ("Stanton3_Area18", "Baijini Point"),
    ("Stanton4_NewBabbage", "Port Tressler"),
):
    station_preview_parser = GameLogLocationParser(mappings)
    station_preview_parser.parse_update(
        f"<RequestLocationInventory> Player[ValidationOnly] requested inventory for Location[{physical_token}]"
    )
    station_preview_parser.begin_map_session()
    station_preview = station_preview_parser.parse_update(
        "<Player Requested Fuel to Quantum Target - Local> destination ObjectContainer_RestStop"
    )
    if station_preview is None or station_preview.detection.name != expected_station:
        raise RuntimeError(f"Prévisualisation orbitale manquante : {expected_station}.")

site_parser = GameLogLocationParser(mappings)
known_site = site_parser.parse_update(
    "Player has selected point Vivere PAF-I as their destination, routing locally"
)
if known_site is None or known_site.detection.name != "Vivere PAF-I":
    raise RuntimeError("Un nom Astro Atlas contenant des espaces n'est pas lu dans la route.")
site_parser = GameLogLocationParser(mappings)
site_parser.parse_update(
    "<Player Requested Fuel to Quantum Target - Local> destination OOC_Stanton1b_Aberdeen"
)
unknown_site = site_parser.parse_update(
    "Adding surface location NavPoint_Dynamic_729514324095 to end of route. New final index 2"
)
if (
    unknown_site is None
    or unknown_site.detection.name != "No data available"
    or unknown_site.detection.body != "Aberdeen"
):
    raise RuntimeError("Une route de surface opaque laisse l'ancienne ville affichée.")

# Starmap close and delayed-event suppression.
map_parser = GameLogLocationParser(mappings)
map_parser.parse_update(
    "<RequestLocationInventory> Player[ValidationOnly] requested inventory for Location[Stanton1_Lorville]"
)
map_parser.begin_map_session()
preview = map_parser.parse_update(
    "<Player Requested Fuel to Quantum Target - Local> destination OOC_Stanton_2_Crusader"
)
if preview is None or preview.detection.travel_state != "map_preview":
    raise RuntimeError("La prévisualisation Starmap est invalide.")
physical = map_parser.force_current_position()
if physical is None or physical.detection.name != "Lorville":
    raise RuntimeError("Échap/F2 ne restaure pas la position physique.")
delayed = map_parser.parse_update(
    "Player has selected point OOC_Stanton_2_Crusader as their destination"
)
if delayed is not None:
    raise RuntimeError("Un événement Starmap retardé rouvre la prévisualisation.")
map_parser.begin_map_session()
fresh_preview = map_parser.parse_update(
    "Player has selected point OOC_Stanton_1a_Ariel as their destination"
)
if fresh_preview is None or fresh_preview.detection.name != "Arial":
    raise RuntimeError("Une nouvelle session F2 ne réactive pas la Starmap.")

# QT display priority and cancellation.
qt_parser = GameLogLocationParser(mappings)
qt_parser.parse_update(
    "<Player Requested Fuel to Quantum Target - Local> destination OOC_Stanton_4a_Calliope"
)
started = qt_parser.commit_quantum_destination()
if started is None or started.detection.name != "Calliope":
    raise RuntimeError("La destination QT n'est pas verrouillée.")
context = qt_parser.parse_update('Added notification "Exited Monitored Space: "')
if context is None or context.detection.name != "Calliope" or qt_parser.monitored_state != "unmonitored":
    raise RuntimeError("Le contexte QT non surveillé est incorrect.")
cancelled = qt_parser.parse_update("<Failed to get starmap route data!> No Route loaded!")
if cancelled is None or cancelled.detection.name != "Deep Space":
    raise RuntimeError("Une annulation QT engagée ne passe pas en Deep Space.")

if secondary_display(
    location_name="Calliope",
    weather="Neige",
    travel_state="quantum_destination",
    jurisdiction="",
    monitored_state="unmonitored",
    unknown_site=False,
    station=False,
    exact_site=False,
) != "":
    raise RuntimeError("Le champ secondaire doit rester vide hors météo planétaire.")

# Public Real Time Checker: choose the physical code over a newer Starmap destination and
# write exactly one shareable JSON file only after a manual Wi-Fi confirmation.
with tempfile.TemporaryDirectory(prefix="public-real-time-checker-") as temp_dir:
    parser_root = Path(temp_dir)
    recorder = PublicParserRecorder(root=parser_root)
    recorder.start_session(Path("C:/Games/StarCitizen/LIVE/Game.log"))
    recorder.observe_line(
        "<2026-07-28T09:59:59.000Z> <RequestLocationInventory> "
        "Player[ValidationOnly] requested inventory for Location[Stanton4_NewBabbage]"
    )
    recorder.observe_line(
        "<2026-07-28T10:00:00.000Z> <Update Inventory Location> "
        "Player [ValidationOnly] is changing location. Landing [0] -> [0]. "
        "Location [4167598756] -> [3170699229]"
    )
    recorder.observe_line(
        "<2026-07-28T10:00:01.000Z> Player has selected point "
        "OOC_Stanton_2_Crusader as their destination"
    )
    capture = recorder.confirm_location("New Babbage Commons")
    if not capture.get("saved") or capture.get("location_code") != "3170699229":
        raise RuntimeError("Public Real Time Checker ne sélectionne pas le code physique le plus probable.")
    generated = sorted(path.name for path in parser_root.iterdir() if path.is_file())
    if generated != ["Public_Real_Time_Checker_Registry.json"]:
        raise RuntimeError(f"Public Real Time Checker génère des fichiers inutiles : {generated!r}")
    registry = json.loads((parser_root / generated[0]).read_text(encoding="utf-8"))
    records = registry.get("records") if isinstance(registry, dict) else None
    if not isinstance(records, list) or len(records) != 1:
        raise RuntimeError("Le registre Public Real Time Checker est invalide.")
    record = records[0]
    if record.get("user_location") != "New Babbage Commons" or record.get("location_code") != "3170699229":
        raise RuntimeError("Le texte utilisateur et le code Game.log ne sont pas associés.")
    forbidden_keys = {"game_log_path", "player_name", "account_id", "full_log"}
    if forbidden_keys.intersection(record):
        raise RuntimeError("Le fichier Public Real Time Checker contient des données interdites.")


for identity_fragment in (
    'app.setApplicationName("Public Real Time Checker")',
    'app.setApplicationDisplayName("Public Real Time Checker")',
):
    if identity_fragment not in package_root.joinpath("__main__.py").read_text(encoding="utf-8"):
        raise RuntimeError(f"Identité visible absente : {identity_fragment}")
if 'Path(roaming) / "PublicRealTimeChecker"' not in package_root.joinpath("config.py").read_text(encoding="utf-8"):
    raise RuntimeError("Le stockage de configuration n'est pas isolé de SC RTLT.")
if 'Public_Real_Time_Checker_Registry.json' not in package_root.joinpath("public_parser_recorder.py").read_text(encoding="utf-8"):
    raise RuntimeError("Le registre Public Real Time Checker n'est pas correctement nommé.")

settings_source = package_root.joinpath("settings_page.py").read_text(encoding="utf-8")
for required_fragment in (
    't("Détection automatique via Game.log", "Automatic detection through Game.log")',
    't("Utiliser une ville par défaut", "Use a default city")',
    "self.location_mode_group.setExclusive(True)",
    "self.location.setEnabled(self.use_default_location.isChecked())",
    '"game_log/location_mode", "automatic" if automatic_location else "default_city"',
    'self.language.addItem("Français", "fr")',
    'self.language.addItem("English", "en")',
    'self.settings.setValue("app/language"',
    't("Fichier Public Real Time Checker", "Public Real Time Checker file")',
    "public_parser_output_path()",
):
    if required_fragment not in settings_source:
        raise RuntimeError(f"Réglage obligatoire absent : {required_fragment}")
if 'self.settings.setValue("game_log/manual_override_pending"' in settings_source:
    raise RuntimeError("L'ancien cumul ville manuelle + détection automatique est encore actif.")
for forbidden_fragment in (
    "record_location_tests",
    "Enregistrer automatiquement les identifiants",
    "location_test_directory",
):
    if forbidden_fragment in settings_source:
        raise RuntimeError(f"Ancien enregistrement passif encore présent : {forbidden_fragment}")
widget_source = package_root.joinpath("companion_widget.py").read_text(encoding="utf-8")
if (
    'data["location"] = tr(self.settings, "No data available", "No data available")' not in widget_source
    or 'elif automatic:' not in widget_source
    or 'def retranslate_ui(self)' not in widget_source
):
    raise RuntimeError("Le mode automatique ou la traduction dynamique du widget est invalide.")
language_source = package_root.joinpath("language.py")
if not language_source.is_file():
    raise RuntimeError("Le module de langue FR/EN est absent du paquet.")

class _LanguageSettings:
    def __init__(self, language: str) -> None:
        self.language = language

    def value(self, key, defaultValue=None, type=None):  # noqa: A002
        value = self.language if key == "app/language" else defaultValue
        return type(value) if type else value

if current_language(_LanguageSettings("en")) != "en":
    raise RuntimeError("Le réglage English n'est pas reconnu.")
if tr(_LanguageSettings("en"), "Réglages", "Settings") != "Settings":
    raise RuntimeError("La traduction anglaise générique est invalide.")
if translate_weather("snow", daylight=True, language="en") != "Snow":
    raise RuntimeError("La météo anglaise du widget est invalide.")
if translate_location_name("Atmosphère de Clio", "en") != "Clio Atmosphere":
    raise RuntimeError("La traduction des lieux génériques est invalide.")

location_source = package_root.joinpath("game_log_location.py").read_text(encoding="utf-8")
for required_fragment in (
    "self._physical_position",
    "def begin_map_session",
    "def _local_orbital_station_from_context",
    '"hurston": "Everus Harbor"',
    '"crusader": "Seraphim Station"',
    '"arccorp": "Baijini Point"',
    '"microtech": "Port Tressler"',
):
    if required_fragment not in location_source:
        raise RuntimeError(f"Séparation physique/Starmap ou station orbitale absente : {required_fragment}")
main_window_source = package_root.joinpath("main_window.py").read_text(encoding="utf-8")
for required_fragment in (
    "self.game_log_monitor.map_session_open",
    "self.game_log_monitor.begin_map_session()",
    "self.game_log_monitor.force_current_position()",
):
    if required_fragment not in main_window_source:
        raise RuntimeError(f"Gestion F2/Échap absente : {required_fragment}")

# Construct the actual HUD once. This catches startup-only regressions such as
# invalid translation calls before the installer activates the new release.
app = QApplication.instance() or QApplication(["Public Real Time Checker runtime verification"])
with tempfile.TemporaryDirectory(prefix="sc-rtlt-widget-") as temp_dir:
    widget_settings = QSettings(str(Path(temp_dir) / "settings.ini"), QSettings.Format.IniFormat)
    widget_settings.setValue("game_log/auto_location_enabled", False)
    from sc_web_companion.widget_window import WidgetWindow

    widget = WidgetWindow(widget_settings)
    widget.page.refresh_time()
    widget.close()
    widget.deleteLater()
app.processEvents()

print(
    "Validation runtime OK — "
    f"Public Real Time Checker {sc_web_companion.__version__}, PySide6 {PySide6.__version__}"
)
