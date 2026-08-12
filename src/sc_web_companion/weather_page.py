from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .verse_time import LOCATION_BY_ID, VERSE_LOCATIONS, VerseClockLocation
from .weather_simulation import simulate_weather

# Compatibility aliases kept for existing imports and saved settings.
VerseLocation = VerseClockLocation


def estimate_verse_weather(location_id: str, moment=None) -> dict[str, object]:
    """Legacy function name kept for migration; now returns simulated widget weather."""
    return simulate_weather(location_id, moment)


class WeatherPage(QWidget):
    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings

        self.location_combo = QComboBox()
        for location in VERSE_LOCATIONS:
            self.location_combo.addItem(location.label, location.location_id)
        saved = self.settings.value("verse_time/location", "", type=str)
        if not saved:
            saved = self.settings.value("verse_weather/location", "new-babbage", type=str)
        self.location_combo.setCurrentIndex(max(0, self.location_combo.findData(saved)))
        self.location_combo.currentIndexChanged.connect(self.refresh)

        self.refresh_button = QPushButton("Actualiser")
        self.refresh_button.setObjectName("smallButton")
        self.refresh_button.clicked.connect(self.refresh)

        header = QHBoxLayout()
        header.addWidget(self.location_combo, 1)
        header.addWidget(self.refresh_button)

        self.body_label = QLabel("microTech")
        self.body_label.setObjectName("weatherBody")
        self.time_label = QLabel("--:--")
        self.time_label.setObjectName("weatherTemperature")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label = QLabel("Calcul de l'heure locale Star Citizen")
        self.phase_label.setObjectName("weatherCondition")
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.source_card = QFrame()
        self.source_card.setObjectName("weatherDetails")
        source_layout = QVBoxLayout(self.source_card)
        source_layout.setContentsMargins(14, 12, 14, 12)
        source = QLabel(
            "Source : heure locale calculée avec VerseTime, puis météo décorative simulée côté application. "
            "Aucune donnée live de shard, température réelle ou API météo n'est utilisée."
        )
        source.setWordWrap(True)
        source_layout.addWidget(source)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addStretch(1)
        layout.addWidget(self.body_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label)
        layout.addWidget(self.phase_label)
        layout.addStretch(1)
        layout.addWidget(self.source_card)

        self.timer = QTimer(self)
        self.timer.setInterval(15_000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        location_id = str(self.location_combo.currentData() or "new-babbage")
        self.settings.setValue("verse_time/location", location_id)
        self.settings.setValue("verse_weather/location", location_id)
        data = simulate_weather(location_id)
        self.body_label.setText(f"{data['location']} · {data['body']}")
        self.time_label.setText(str(data["local_time"]))
        self.phase_label.setText(
            f"{data['phase']} · {data['weather_display']} · météo décorative simulée"
        )
