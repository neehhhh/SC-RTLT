from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .radio_engine import HCN_STREAM_URLS, RECREG_STREAM_URLS, RadioEngine


@dataclass(frozen=True, slots=True)
class RadioStation:
    station_id: str
    name: str
    frequency: str
    tagline: str
    stream_candidates: tuple[str, ...]

    @property
    def display_name(self) -> str:
        return f"{self.name} · {self.frequency}"


RADIO_STATIONS: tuple[RadioStation, ...] = (
    RadioStation(
        "radio1",
        "HCN-Radio 1",
        "305.5",
        "Voices of the Universe",
        (HCN_STREAM_URLS[0],),
    ),
    RadioStation(
        "radio2",
        "HCN-Radio 2",
        "315.0",
        "Diverse Sounds of the Stars",
        (HCN_STREAM_URLS[1],),
    ),
    RadioStation(
        "investigative",
        "HCN-Investigative",
        "319.7",
        "Uncovering Hidden Truths",
        (HCN_STREAM_URLS[2],),
    ),
    RadioStation(
        "beats",
        "HCN-Beats",
        "320.0",
        "Galactic Grooves",
        (HCN_STREAM_URLS[3],),
    ),
    RadioStation(
        "classical",
        "HCN-Classical",
        "317.9",
        "Timeless Compositions Across the Verse",
        (HCN_STREAM_URLS[4],),
    ),
    RadioStation(
        "peoples-radio",
        "The People's Radio",
        "NYX",
        "The Hottest Mix from a Small Rock in Nyx",
        (
            "http://us1.streamingpulse.com:7058/stream",
            "https://us7.streamingpulse.com/4232/?pl=vlc&c=TPR",
        ),
    ),
    RadioStation(
        "recreg-rock",
        "REC·REG — Rock",
        "101.1 MHz",
        "Classic and modern rock hits · Port Olisar, Crusader",
        (RECREG_STREAM_URLS[0],),
    ),
    RadioStation(
        "recreg-western",
        "REC·REG — Western",
        "102.3 MHz",
        "Country and western vibes · Levski, Delamar",
        (RECREG_STREAM_URLS[1],),
    ),
    RadioStation(
        "recreg-punk",
        "REC·REG — Punk",
        "103.7 MHz",
        "Punk rock and underground sounds · Ruin Station, Pyro",
        (RECREG_STREAM_URLS[2],),
    ),
    RadioStation(
        "recreg-lounge",
        "REC·REG — Lounge",
        "104.5 MHz",
        "Smooth lounge and chill beats · New Babbage, microTech",
        (RECREG_STREAM_URLS[3],),
    ),
    RadioStation(
        "recreg-metal",
        "REC·REG — Metal",
        "105.9 MHz",
        "Heavy metal and hard rock · Area18, ArcCorp",
        (RECREG_STREAM_URLS[4],),
    ),
    RadioStation(
        "recreg-country",
        "REC·REG — Country",
        "106.7 MHz",
        "Country classics and modern hits · Lorville, Hurston",
        (RECREG_STREAM_URLS[5],),
    ),
    RadioStation(
        "recreg-groovy",
        "REC·REG — Groovy",
        "107.5 MHz",
        "Funky grooves and smooth vibes · Terra Prime, Terra",
        (RECREG_STREAM_URLS[6],),
    ),
    RadioStation(
        "recreg-old-times",
        "REC·REG — Old Times",
        "108.3 MHz",
        "Classic oldies and nostalgic hits · Orison, Crusader",
        (RECREG_STREAM_URLS[7],),
    ),
)
# Compatibility alias for external callers that imported the historical name.
HCN_STATIONS = RADIO_STATIONS
STATION_BY_ID = {station.station_id: station for station in RADIO_STATIONS}
DEFAULT_STATION_ID = "radio2"


def station_streams(_settings: QSettings, station: RadioStation) -> tuple[str, ...]:
    return station.stream_candidates


def station_stream(settings: QSettings, station: RadioStation) -> str:
    streams = station_streams(settings, station)
    return streams[0] if streams else ""


def playable_stations(_settings: QSettings) -> list[RadioStation]:
    return list(RADIO_STATIONS)


def station_from_settings(settings: QSettings) -> RadioStation:
    station_id = settings.value("radio/station", DEFAULT_STATION_ID, type=str)
    return STATION_BY_ID.get(station_id, STATION_BY_ID[DEFAULT_STATION_ID])


class RadioPage(QWidget):
    """Full-page native player and audio diagnostic for all configured stations."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.station = station_from_settings(settings)
        self.engine = RadioEngine(
            self.settings.value("radio/volume", 35, type=int),
            self,
            self.settings.value("radio/output_device", "", type=str),
        )
        self.engine.state_changed.connect(self._state_changed)
        self.engine.error.connect(lambda message: self.status.setText(f"Erreur audio : {message}"))
        self.engine.stream_changed.connect(self._stream_changed)

        self.title = QLabel(self.station.name)
        self.title.setObjectName("homeTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("homeSubtitle")
        self.subtitle.setWordWrap(True)

        self.station_combo = QComboBox()
        for station in RADIO_STATIONS:
            self.station_combo.addItem(station.display_name, station.station_id)
        self.station_combo.setCurrentIndex(self.station_combo.findData(self.station.station_id))
        self.station_combo.currentIndexChanged.connect(self._station_changed)

        self.previous_button = QPushButton("Précédente")
        self.previous_button.clicked.connect(lambda: self.change_station(-1))
        self.next_button = QPushButton("Suivante")
        self.next_button.clicked.connect(lambda: self.change_station(1))
        self.play_button = QPushButton("Lecture")
        self.play_button.setObjectName("primaryButton")
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.engine.stop)
        self.test_button = QPushButton("Tester le son Windows")
        self.test_button.clicked.connect(self._test_output)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(self.settings.value("radio/volume", 35, type=int))
        self.volume.valueChanged.connect(self._volume_changed)
        self.status = QLabel(
            "Commence par « Tester le son Windows ». Si ce son est audible mais pas la radio, "
            "le problème vient du flux radio et non des haut-parleurs."
        )
        self.status.setWordWrap(True)
        self.status.setObjectName("homeSubtitle")

        station_row = QHBoxLayout()
        station_row.addWidget(self.previous_button)
        station_row.addWidget(self.station_combo, 1)
        station_row.addWidget(self.next_button)

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.test_button)
        controls.addWidget(QLabel("Volume"))
        controls.addWidget(self.volume, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addLayout(station_row)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self._refresh_station_labels()

    def current_station(self) -> RadioStation:
        station_id = str(self.station_combo.currentData() or DEFAULT_STATION_ID)
        return STATION_BY_ID.get(station_id, STATION_BY_ID[DEFAULT_STATION_ID])

    def change_station(self, delta: int) -> None:
        count = self.station_combo.count()
        if count:
            self.station_combo.setCurrentIndex((self.station_combo.currentIndex() + delta) % count)

    def _station_changed(self) -> None:
        self.station = self.current_station()
        self.settings.setValue("radio/station", self.station.station_id)
        self.settings.sync()
        self._refresh_station_labels()
        if self.engine.state in {"playing", "connecting"}:
            self.engine.play(self.station.stream_candidates)
        else:
            self.status.setText(f"{self.station.name} prête.")

    def _refresh_station_labels(self) -> None:
        self.title.setText(self.station.name)
        self.subtitle.setText(
            f"{self.station.tagline} · {self.station.frequency}. "
            "Lecteur natif Windows utilisant le flux direct de cette station."
        )

    def toggle_playback(self) -> None:
        self.engine.toggle(self.station.stream_candidates)

    def _test_output(self) -> None:
        self.engine.test_output()
        self.status.setText("Test local lancé : un son bref doit être audible.")

    def _volume_changed(self, value: int) -> None:
        self.settings.setValue("radio/volume", value)
        self.settings.sync()
        self.engine.set_volume(value)

    def _stream_changed(self, _url: str) -> None:
        self.status.setText(f"Connexion à {self.station.name} en cours…")

    def _state_changed(self, state: str) -> None:
        labels = {
            "connecting": f"Connexion à {self.station.name}…",
            "playing": f"Lecture · {self.station.name}",
            "paused": "En pause",
            "stopped": "Lecture arrêtée",
            "error": f"Le flux direct de {self.station.name} n'a pas répondu.",
        }
        self.status.setText(labels.get(state, state))
        self.play_button.setText("Pause" if state in {"playing", "connecting"} else "Lecture")

    def apply_external_settings(self) -> None:
        volume = self.settings.value("radio/volume", 35, type=int)
        self.volume.setValue(max(0, min(100, volume)))
        self.engine.set_volume(volume)
        self.engine.set_output_device(self.settings.value("radio/output_device", "", type=str))
        station = station_from_settings(self.settings)
        index = self.station_combo.findData(station.station_id)
        if index >= 0:
            blocker = QSignalBlocker(self.station_combo)
            self.station_combo.setCurrentIndex(index)
            del blocker
            self.station = station
            self._refresh_station_labels()

    def shutdown(self) -> None:
        self.engine.shutdown()
