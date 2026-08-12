APP_STYLE = """
QWidget {
    background: #10151b;
    color: #eef3f7;
    font-family: "Bahnschrift", "Arial Narrow", "Segoe UI";
    font-size: 10pt;
}
QWidget#header {
    background: #151c24;
    border-bottom: 1px solid #2a3541;
}
QLabel#appTitle { font-size: 15pt; font-weight: 700; }
QLabel#appSubtitle, QLabel#homeSubtitle, QLabel#browserStatus,
QLabel#weatherStatus, QLabel#radioStatus { color: #9eabb8; }
QLabel#homeTitle { font-size: 25pt; font-weight: 700; }
QLabel#dialogTitle { font-size: 16pt; font-weight: 700; }
QLabel#headerWidgetLabel { color: #aeb8c2; }
QListWidget {
    background: #0c1116;
    border: none;
    border-right: 1px solid #25303a;
    padding: 8px;
    outline: none;
}
QListWidget::item { padding: 11px 10px; margin: 2px 0; border-radius: 6px; }
QListWidget::item:selected { background: #263645; color: white; }
QPushButton {
    background: #202c37;
    border: 1px solid #364554;
    border-radius: 6px;
    padding: 7px 11px;
}
QPushButton:hover { background: #2a3946; }
QPushButton:disabled { color: #6f7b86; background: #171f27; }
QPushButton#primaryButton { background: #2f5871; border-color: #467996; }
QPushButton#smallButton { padding: 4px 8px; min-height: 18px; }
QPushButton#widgetCloseButton {
    background: rgba(255,255,255,25);
    border: 1px solid rgba(255,255,255,35);
    border-radius: 12px;
    padding: 0;
    font-size: 13pt;
    font-weight: 600;
}
QPushButton#widgetCloseButton:hover { background: rgba(170,55,65,190); }
QPushButton#mediaButton {
    background: rgba(255,255,255,28);
    border: 1px solid rgba(255,255,255,35);
    border-radius: 7px;
    padding: 2px;
}
QPushButton#mediaButton:hover { background: rgba(255,255,255,52); }
QLineEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox {
    background: #0d1319;
    border: 1px solid #344250;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #315d78;
}
QComboBox::drop-down { border: none; width: 24px; }
QFrame#settingsSection {
    background: #151d25;
    border: 1px solid #2a3742;
    border-radius: 9px;
}
QLabel#settingsTitle { font-size: 13pt; font-weight: 700; }
QFrame#companionCard {
    background: transparent;
    border: none;
}
QComboBox#widgetLocationCombo, QComboBox#widgetStationCombo {
    background: transparent;
    border: none;
    color: white;
    padding: 0 18px 0 0;
}
QComboBox#widgetLocationCombo { font-size: 15pt; font-weight: 600; }
QComboBox#widgetStationCombo { font-size: 9.5pt; font-weight: 600; }
QComboBox#widgetLocationCombo QAbstractItemView,
QComboBox#widgetStationCombo QAbstractItemView {
    background: #2a2d34;
    color: white;
    selection-background-color: #4d6274;
}
QLabel#widgetCondition { color: rgba(255,255,255,210); font-size: 9.5pt; }
QLabel#widgetModeLabel { color: rgba(255,255,255,210); font-size: 8.5pt; }
QLabel#widgetFrequency { color: rgba(255,255,255,210); font-size: 8.5pt; }
QLabel#widgetTemperature { color: white; }
QLabel#widgetVolumeValue, QLabel#widgetStatus { color: rgba(255,255,255,195); font-size: 8pt; }
QFrame#companionCard QSlider::groove:horizontal {
    height: 4px;
    background: rgba(255,255,255,60);
    border-radius: 2px;
}
QFrame#companionCard QSlider::sub-page:horizontal {
    background: rgba(255,255,255,210);
    border-radius: 2px;
}
QFrame#companionCard QSlider::handle:horizontal {
    width: 12px;
    margin: -4px 0;
    background: white;
    border-radius: 6px;
}
QSlider::groove:horizontal { height: 5px; background: #27333e; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #7fa9c1; border-radius: 7px; }
QScrollBar:vertical { background: #0d1218; width: 10px; }
QScrollBar::handle:vertical { background: #35424e; min-height: 30px; border-radius: 5px; }
"""

# Keep every child of the glass widget transparent despite the global app background.
APP_STYLE += """
QFrame#companionCard QWidget,
QFrame#companionCard QLabel {
    background: transparent;
}
"""
