from __future__ import annotations

import math
import tempfile
import urllib.parse
import wave
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaMetaData, QMediaPlayer

from .metadata_text import clean_metadata_text
from .stream_metadata import StreamMetadataPoller


# Direct HCN endpoints supplied by the broadcaster. Each station has one
# dedicated stream; the UI maps these URLs to the official station names.
HCN_STREAM_URLS: tuple[str, ...] = (
    "https://hcnradio.ddns.me/stream/1/",
    "https://hcnradio.ddns.me/stream/2/",
    "https://hcnradio.ddns.me/stream/3/",
    "https://hcnradio.ddns.me/stream/4/",
    "https://hcnradio.ddns.me/stream/5/",
)

# Kept as the engine default for callers that do not explicitly select a
# station. Normal application playback always passes the selected station URL.
DEFAULT_HCN_STREAMS: tuple[str, ...] = (HCN_STREAM_URLS[0],)


def _device_key(device) -> str:
    try:
        return bytes(device.id()).hex()
    except Exception:
        try:
            return bytes(device.id().toHex()).decode("ascii")
        except Exception:
            return ""


def available_output_devices() -> list[tuple[str, str]]:
    """Return native Qt audio outputs. An empty key means Windows default."""
    result: list[tuple[str, str]] = []
    try:
        for device in QMediaDevices.audioOutputs():
            result.append((device.description(), _device_key(device)))
    except Exception:
        return []
    return result


def _find_output_device(key: str):
    normalized = str(key or "").strip().lower()
    if not normalized:
        return QMediaDevices.defaultAudioOutput()
    try:
        for device in QMediaDevices.audioOutputs():
            if _device_key(device).lower() == normalized:
                return device
    except Exception:
        pass
    return QMediaDevices.defaultAudioOutput()


def _tone_file() -> Path:
    """Create a short local WAV used to test the Windows audio output."""
    path = Path(tempfile.gettempdir()) / "sc-web-companion-audio-test.wav"
    if path.exists() and path.stat().st_size > 1_000:
        return path
    sample_rate = 44_100
    duration = 0.75
    frequency = 523.25
    frames = int(sample_rate * duration)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        data = bytearray()
        for index in range(frames):
            envelope = min(1.0, index / 1_200.0, (frames - index) / 2_200.0)
            sample = int(11_000 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
            packed = int(sample).to_bytes(2, "little", signed=True)
            data.extend(packed)
            data.extend(packed)
        wav.writeframes(bytes(data))
    return path


DEFAULT_UI_VOLUME = 35
MAX_OUTPUT_GAIN = 0.50


class RadioEngine(QObject):
    """Native Qt radio player with stream fallback and a local audio test."""

    state_changed = Signal(str)
    error = Signal(str)
    stream_changed = Signal(str)
    test_started = Signal()
    track_changed = Signal(str, str)
    metadata_status_changed = Signal(str)

    def __init__(self, volume: int = DEFAULT_UI_VOLUME, parent: QObject | None = None, output_device: str = "") -> None:
        super().__init__(parent)
        self._state = "stopped"
        self._volume = max(0, min(100, int(volume)))
        self._output_device = str(output_device or "").strip()
        self._candidates: list[str] = []
        self._candidate_index = -1
        self._manual_stop = False
        self._advance_scheduled = False
        self._track_artist = ""
        self._track_title = ""
        self._raw_metadata_authoritative = False

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(self._effective_level(self._volume))
        self.audio_output.setDevice(_find_output_device(self._output_device))

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.playbackStateChanged.connect(self._on_playback_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.metaDataChanged.connect(self._on_metadata_changed)

        self.metadata_poller = StreamMetadataPoller(self)
        self.metadata_poller.metadata_found.connect(self._on_stream_metadata)
        self.metadata_poller.status_changed.connect(self.metadata_status_changed)

        self.connect_timeout = QTimer(self)
        self.connect_timeout.setSingleShot(True)
        self.connect_timeout.setInterval(12_000)
        self.connect_timeout.timeout.connect(self._try_next_candidate)

        self.test_audio_output = QAudioOutput(self)
        self.test_audio_output.setVolume(self._effective_level(self._volume))
        self.test_audio_output.setDevice(_find_output_device(self._output_device))
        self.test_player = QMediaPlayer(self)
        self.test_player.setAudioOutput(self.test_audio_output)

    @property
    def state(self) -> str:
        return self._state

    @property
    def has_track_metadata(self) -> bool:
        return bool(self._track_title or self._track_artist)

    @property
    def current_url(self) -> str:
        if 0 <= self._candidate_index < len(self._candidates):
            return self._candidates[self._candidate_index]
        return ""

    @property
    def candidate_count(self) -> int:
        return len(self._candidates)

    def _set_state(self, state: str) -> None:
        if self._state == state:
            return
        self._state = state
        self.state_changed.emit(state)

    @staticmethod
    def _normalize_candidates(urls: str | Iterable[str] | None) -> list[str]:
        if urls is None:
            raw = list(DEFAULT_HCN_STREAMS)
        elif isinstance(urls, str):
            raw = [urls]
        else:
            raw = list(urls)
        result: list[str] = []
        for value in raw:
            url = str(value or "").strip()
            if url and url not in result:
                result.append(url)
        return result

    def play(self, urls: str | Iterable[str] | None = None) -> None:
        candidates = self._normalize_candidates(urls)
        if not candidates:
            self.error.emit("Aucun flux HCN disponible.")
            self._set_state("error")
            return
        self.connect_timeout.stop()
        self._advance_scheduled = False
        self._manual_stop = False
        self.player.stop()
        self.metadata_poller.stop()
        self._clear_track()
        self._raw_metadata_authoritative = False
        self._candidates = candidates
        self._candidate_index = -1
        self._set_state("connecting")
        self._try_next_candidate()

    def _schedule_next_candidate(self) -> None:
        if self._manual_stop or self._advance_scheduled:
            return
        self._advance_scheduled = True
        QTimer.singleShot(0, self._try_next_candidate)

    def _try_next_candidate(self) -> None:
        self._advance_scheduled = False
        self.connect_timeout.stop()
        if self._manual_stop:
            return
        self._candidate_index += 1
        if self._candidate_index >= len(self._candidates):
            self.player.stop()
            self._set_state("error")
            self.error.emit(
                "Aucun flux HCN n'a répondu. Utilise d'abord le test audio local pour vérifier Windows."
            )
            return
        url = self._candidates[self._candidate_index]
        self._raw_metadata_authoritative = False
        self.stream_changed.emit(url)
        self._set_state("connecting")
        self.player.setSource(QUrl(url))
        self.player.play()
        self.metadata_poller.start(url)
        self.connect_timeout.start()

    def toggle(self, urls: str | Iterable[str] | None = None) -> None:
        if self._state in {"playing", "connecting"}:
            self.pause()
        elif self._state == "paused":
            self._manual_stop = False
            self.player.play()
            if self.current_url:
                self.metadata_poller.start(self.current_url)
            self.connect_timeout.start()
        else:
            self.play(urls)

    def pause(self) -> None:
        self.connect_timeout.stop()
        self._manual_stop = True
        self.player.pause()
        self.metadata_poller.pause()
        self._set_state("paused")

    def stop(self, emit_state: bool = True) -> None:
        self.connect_timeout.stop()
        self._advance_scheduled = False
        self._manual_stop = True
        self.player.stop()
        self.metadata_poller.stop()
        if emit_state:
            self._set_state("stopped")

    @staticmethod
    def _effective_level(value: int) -> float:
        normalized = max(0.0, min(1.0, int(value) / 100.0))
        # Keep the user-facing slider simple while taming loud HCN output.
        return min(1.0, MAX_OUTPUT_GAIN * (normalized ** 1.35))

    def set_volume(self, value: int) -> None:
        self._volume = max(0, min(100, int(value)))
        level = self._effective_level(self._volume)
        self.audio_output.setVolume(level)
        self.test_audio_output.setVolume(level)

    def set_output_device(self, value: str) -> None:
        self._output_device = str(value or "").strip()
        device = _find_output_device(self._output_device)
        self.audio_output.setDevice(device)
        self.test_audio_output.setDevice(device)

    def test_output(self) -> None:
        self.test_audio_output.setDevice(_find_output_device(self._output_device))
        self.test_audio_output.setVolume(max(0.12, self._effective_level(self._volume)))
        self.test_player.setSource(QUrl.fromLocalFile(str(_tone_file())))
        self.test_player.play()
        self.test_started.emit()

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.connect_timeout.stop()
            self._set_state("playing")
            self.metadata_poller.probe_now()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._set_state("paused")
        elif self._manual_stop and self._state != "paused":
            self._set_state("stopped")

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in {
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.LoadedMedia,
        } and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.connect_timeout.stop()
            self._set_state("playing")
        elif status in {
            QMediaPlayer.MediaStatus.InvalidMedia,
            QMediaPlayer.MediaStatus.NoMedia,
            QMediaPlayer.MediaStatus.EndOfMedia,
        }:
            self._schedule_next_candidate()

    @staticmethod
    def _clean_metadata_value(value) -> str:
        return clean_metadata_text(value)

    @classmethod
    def split_stream_title(cls, raw_title: str, raw_artist: str = "") -> tuple[str, str]:
        title = cls._clean_metadata_value(raw_title)
        artist = cls._clean_metadata_value(raw_artist)
        # Most Icecast/Shoutcast stations expose a single StreamTitle field as
        # "Artist - Title". Preserve legitimate hyphens by splitting once.
        if not artist:
            for separator in (" — ", " – ", " - "):
                if separator in title:
                    left, right = title.split(separator, 1)
                    if left.strip() and right.strip():
                        artist, title = left.strip(), right.strip()
                        break
        return artist, title

    def _metadata_text(self, metadata: QMediaMetaData, key: QMediaMetaData.Key) -> str:
        try:
            return self._clean_metadata_value(metadata.value(key))
        except Exception:
            try:
                return self._clean_metadata_value(metadata.stringValue(key))
            except Exception:
                return ""

    def _native_metadata_is_disabled(self) -> bool:
        """Use raw ICY bytes for Streaming Pulse instead of Qt's decoded text."""
        try:
            host = (urllib.parse.urlsplit(self.current_url).hostname or "").casefold()
        except Exception:
            host = ""
        return host == "streamingpulse.com" or host.endswith(".streamingpulse.com")

    def _on_metadata_changed(self) -> None:
        if self._raw_metadata_authoritative or self._native_metadata_is_disabled():
            return
        metadata = self.player.metaData()
        title = self._metadata_text(metadata, QMediaMetaData.Key.Title)
        artist = ""
        for key in (
            QMediaMetaData.Key.AlbumArtist,
            QMediaMetaData.Key.LeadPerformer,
            QMediaMetaData.Key.ContributingArtist,
            QMediaMetaData.Key.Author,
        ):
            artist = self._metadata_text(metadata, key)
            if artist:
                break
        artist, title = self.split_stream_title(title, artist)
        if not title and not artist:
            return
        if (artist, title) == (self._track_artist, self._track_title):
            return
        self._track_artist, self._track_title = artist, title
        self.track_changed.emit(artist, title)

    def _on_stream_metadata(self, raw_title: str) -> None:
        artist, title = self.split_stream_title(raw_title)
        if not title and not artist:
            return
        self._raw_metadata_authoritative = True
        if (artist, title) == (self._track_artist, self._track_title):
            return
        self._track_artist, self._track_title = artist, title
        self.track_changed.emit(artist, title)

    def _clear_track(self) -> None:
        self._track_artist = ""
        self._track_title = ""
        self.track_changed.emit("", "")

    def _on_player_error(self, _error, _message: str = "") -> None:
        self._schedule_next_candidate()

    def shutdown(self) -> None:
        self.stop()
        self.metadata_poller.shutdown()
        self.test_player.stop()
