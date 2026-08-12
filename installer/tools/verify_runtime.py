from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")


def stage(name: str) -> None:
    print(f"[VERIFY] {name}", flush=True)


def fail(exc: BaseException) -> None:
    print(f"[VERIFY][FAIL] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)


try:
    stage("Import du runtime Qt")
    import PySide6
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: F401
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings  # noqa: F401
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    stage("Import de SC-RTLT Public")
    import sc_web_companion
    from sc_web_companion.party_context import PartyContextParser

    expected_version = sys.argv[1] if len(sys.argv) > 1 else ""
    if not expected_version:
        raise RuntimeError("Version attendue absente de la commande de validation.")
    if sc_web_companion.__version__ != expected_version:
        raise RuntimeError(
            f"Version installée incorrecte : {sc_web_companion.__version__!r}, "
            f"attendu {expected_version!r}."
        )

    stage("Ressources essentielles")
    package_root = files("sc_web_companion")
    for resource_name in (
        "assets/app_icon.png",
        "assets/app_icon.ico",
        "assets/location_mappings.json",
        "widget_window.py",
        "settings_page.py",
        "party_context.py",
        "public_parser_recorder.py",
        "game_log_location.py",
    ):
        if not package_root.joinpath(resource_name).is_file():
            raise FileNotFoundError(f"Ressource absente : {resource_name}")

    stage("Confidentialité des mappings distribués")
    location_catalog = json.loads(
        package_root.joinpath("assets/location_mappings.json").read_text(encoding="utf-8")
    )
    if location_catalog.get("mappings") != []:
        raise RuntimeError(
            "Le build public embarque encore des mappings de localisation issus de sessions utilisateur."
        )
    serialized_catalog = json.dumps(location_catalog, ensure_ascii=False).casefold()
    for forbidden in (
        "wifi_user_confirmed",
        "wifi_user_correction",
        "game_log_projected_start_correlation",
        "request_location_inventory_plus_atc_correlation",
    ):
        if forbidden in serialized_catalog:
            raise RuntimeError(f"Origine utilisateur encore présente dans les mappings : {forbidden}")

    stage("Group UI Alpha")
    settings_source = package_root.joinpath("settings_page.py").read_text(encoding="utf-8")
    widget_source = package_root.joinpath("widget_window.py").read_text(encoding="utf-8")
    for fragment in (
        "Group UI — Alpha",
        "Activer Group UI (Alpha)",
        'self.settings.value("party/group_ui_enabled", False, type=bool)',
        'self.settings.setValue("party/group_ui_enabled", self.group_ui_enabled.isChecked())',
    ):
        if fragment not in settings_source:
            raise RuntimeError(f"Réglage Group UI Alpha incomplet : {fragment}")
    if "Group UI — Player_A" in settings_source or "Group UI Player_A" in settings_source:
        raise RuntimeError("Un placeholder de joueur a remplacé le libellé fonctionnel Alpha.")

    with tempfile.TemporaryDirectory(prefix="sc-rtlt-settings-") as temp_dir:
        ini_path = str(Path(temp_dir) / "settings.ini")
        s1 = QSettings(ini_path, QSettings.Format.IniFormat)
        if s1.value("party/group_ui_enabled", False, type=bool):
            raise RuntimeError("Group UI Alpha n'est pas désactivé par défaut.")
        s1.setValue("party/group_ui_enabled", True)
        s1.sync()
        s2 = QSettings(ini_path, QSettings.Format.IniFormat)
        if not s2.value("party/group_ui_enabled", False, type=bool):
            raise RuntimeError("Le choix Group UI Alpha n'est pas mémorisé entre les sessions.")

    stage("Événements Party fiables")
    parser = PartyContextParser()
    generic_leave = parser.parse_line(
        "[Notice] <Leave group> Client 900000000001 leave group "
        "00000000-0000-0000-0000-000000000000 [Team_GameServices][Social]"
    )
    if generic_leave is None or generic_leave.kind != "generic_group_leave":
        raise RuntimeError("<Leave group> générique est encore confondu avec un départ Party.")

    marker_in = parser.parse_line(
        "<CPartyMarkerComponent RWES> Streamed in party marker TrackedEntityId: 900000000002"
    )
    marker_out = parser.parse_line(
        "<CPartyMarkerComponent UFES> Streaming out party marker TrackedEntityId: 900000000002"
    )
    if marker_in is None or marker_in.kind != "party_marker":
        raise RuntimeError("PartyMarker RWES n'est pas reconnu comme stream-in.")
    if marker_out is None or marker_out.kind != "party_marker_out":
        raise RuntimeError("PartyMarker UFES n'est pas reconnu comme stream-out.")

    launch = parser.parse_line(
        "[Notice] <party-launch> [notification] party-launch from leader[Player_A] : "
        "pendingId[0] gameModeId[-2]"
    )
    if launch is None or launch.kind != "party_launch_offer" or launch.handle != "Player_A":
        raise RuntimeError("party-launch n'est pas isolé du roster Party.")

    custom_parser = PartyContextParser()
    custom_lines = (
        '<2099-01-01T18:32:01.376Z> [Notice] <SHUDEvent_OnNotification> Added notification "New Member Joined',
        "<2099-01-01T18:32:01.376Z> Player_B has joined the group 'Test Channel'.: \" [6] to queue. New queue size: 1",
    )
    if any(custom_parser.parse_line(line) is not None for line in custom_lines):
        raise RuntimeError("Un groupe social personnalisé est encore traité comme Party.")

    independent_channel = parser.parse_line(
        '[Notice] <SHUDEvent_OnNotification> Added notification "You have left the channel \'General Test\'."'
    )
    if independent_channel is None or independent_channel.kind != "independent_channel_activity":
        raise RuntimeError("Un channel indépendant local n'est pas distingué du contexte Party.")

    stage("Barrières source Party")
    party_source = package_root.joinpath("party_context.py").read_text(encoding="utf-8")
    for fragment in (
        'return PartyContextEvent("party_launch_offer", handle)',
        'return PartyContextEvent("generic_group_leave")',
        "Party Launching",
    ):
        if fragment not in party_source:
            raise RuntimeError(f"Barrière de preuve Party absente : {fragment}")

    stage("Démarrage Qt minimal")
    app = QApplication.instance() or QApplication(["SC-RTLT Public runtime verification"])
    app.processEvents()

    from sc_web_companion.widget_window import PartyHudBlock, WidgetWindow  # noqa: F401

    stage("Group UI synthétique")
    party_block = PartyHudBlock("group")
    if not party_block.upsert_group_member("Player_A"):
        raise RuntimeError("Impossible de créer le membre fictif Player_A.")
    if not party_block.upsert_group_member("Player_B"):
        raise RuntimeError("Impossible de créer le membre fictif Player_B.")
    handles = set(party_block.handles())
    if not {"Player_A", "Player_B"}.issubset(handles):
        raise RuntimeError("Les membres fictifs du test Group UI ne sont pas conservés.")

    stage("WAITING FOR RESPONSE")
    pending = PartyHudBlock("group")
    first = pending.add_pending_invitation_key()
    second = pending.add_pending_invitation_key()
    if not first or not second or first == second:
        raise RuntimeError("Les invitations WAITING n'ont pas de clés uniques.")
    if pending.latest_pending_invitation_key() != second:
        raise RuntimeError("Le dernier WAITING n'est pas identifiable.")
    if not pending.remove_pending_invitation(first):
        raise RuntimeError("Impossible d'expirer un WAITING précis.")
    if not pending.has_pending_invitation(second):
        raise RuntimeError("L'expiration d'un WAITING supprime une invitation plus récente.")

    stage("Fixtures de validation uniquement fictives")
    validator_source = Path(__file__).read_text(encoding="utf-8")
    for required_fixture in ("Player_A", "Player_B", "900000000001", "900000000002"):
        if required_fixture not in validator_source:
            raise RuntimeError(f"Fixture fictive de validation absente : {required_fixture}")

    stage("Validation terminée")
    print(
        "Validation runtime OK — "
        f"SC-RTLT Public {sc_web_companion.__version__}, PySide6 {PySide6.__version__}",
        flush=True,
    )
except BaseException as exc:
    fail(exc)
    sys.exit(1)
