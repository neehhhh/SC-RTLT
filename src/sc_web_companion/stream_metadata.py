from __future__ import annotations

import html
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from PySide6.QtCore import QObject, QTimer, Signal

from .metadata_text import clean_metadata_text, decode_metadata_bytes

# The closing ICY delimiter is ``';``. A bare apostrophe inside a song title
# (for example "I Can't Drive 55") is valid and must not end the capture.
_METADATA_PATTERN = re.compile(r"StreamTitle='(.*?)';", re.IGNORECASE | re.DOTALL)
_HCN_HOST = "hcnradio.ddns.me"
_HCN_STREAM_PATTERN = re.compile(r"/stream/(\d+)/?", re.IGNORECASE)
_RECREG_HOST = "radio.recreg.com"
_RECREG_STREAM_PATTERN = re.compile(r"^/listen/[^/]+/radio\.mp3/?$", re.IGNORECASE)
_TPR_METADATA_PAGE = "https://thepeoplesradio.space/peoples_embed/audio-only/"
_TPR_DURATION_SUFFIX = re.compile(r"\s*\[(?:\d{1,2}:)?\d{1,2}:\d{2}\]\s*$")



class _VisibleTextParser(HTMLParser):
    """Collect visible text nodes from the official TPR page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        for line in str(data or "").splitlines():
            value = " ".join(html.unescape(line).split())
            if value:
                self.parts.append(value)


def _is_tpr_stream(stream_url: str) -> bool:
    """Return True only for the two official People's Radio stream forms."""
    try:
        parsed = urllib.parse.urlsplit(stream_url)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
        path = (parsed.path or "/").rstrip("/") or "/"
    except Exception:
        return False
    if host == "us1.streamingpulse.com" and port == 7058 and path == "/stream":
        return True
    return host == "us7.streamingpulse.com" and path == "/4232"


def _is_recreg_stream(stream_url: str) -> bool:
    """Identify only REC·REG's published station MP3 mounts."""
    try:
        parsed = urllib.parse.urlsplit(stream_url)
        host = (parsed.hostname or "").casefold()
        path = parsed.path or "/"
    except Exception:
        return False
    return host == _RECREG_HOST and bool(_RECREG_STREAM_PATTERN.fullmatch(path))


def _extract_tpr_now_playing(page_html: str) -> str:
    """Extract the official site's current track without touching its Unicode."""
    parser = _VisibleTextParser()
    try:
        parser.feed(str(page_html or ""))
        parser.close()
    except Exception:
        return ""

    marker_index = -1
    for index, part in enumerate(parser.parts):
        if part.casefold().rstrip(":") == "now playing":
            marker_index = index
            break
    if marker_index < 0:
        return ""

    stop_markers = {"coming soon", "recently played songs"}
    ignored = {"---", "-", "loading", "loading..."}
    for part in parser.parts[marker_index + 1: marker_index + 25]:
        normalized = part.casefold().rstrip(":")
        if normalized in stop_markers:
            break
        if normalized in ignored:
            continue
        title = _TPR_DURATION_SUFFIX.sub("", part).replace("\x00", "").strip()
        title = " ".join(title.split())
        if _valid_title(title):
            return title
    return ""


def _fetch_tpr_title(timeout: float) -> tuple[bool, str]:
    """Read metadata from TPR's own UTF-8 web page, not the audio headers."""
    request = urllib.request.Request(
        _TPR_METADATA_PAGE,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
            "User-Agent": "SC-RTLT/1.3.6",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            page = decode_metadata_bytes(raw, response.headers)
            return True, _extract_tpr_now_playing(page)
    except Exception:
        return False, ""

def _read_exact(response, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        block = response.read(count - len(chunks))
        if not block:
            break
        chunks.extend(block)
    return bytes(chunks)


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(part for part in (_clean(item) for item in value) if part)
    return clean_metadata_text(value)


def _valid_title(value: str) -> bool:
    return bool(value and value.lower() not in {
        "-", "unknown", "press play to tune in", "none", "null", "offline",
    })


def _song_from_node(node: object) -> str:
    if isinstance(node, str):
        return _clean(node)
    if not isinstance(node, dict):
        return ""
    artist = _clean(node.get("artist") or node.get("performer") or node.get("author"))
    title = _clean(node.get("title") or node.get("name"))
    if artist and title:
        return f"{artist} - {title}"
    for key in (
        "text", "song", "track", "streamtitle", "stream_title", "value",
        "current", "currently_playing", "now_playing", "nowplaying",
    ):
        child = node.get(key)
        value = _song_from_node(child) if isinstance(child, dict) else _clean(child)
        if _valid_title(value):
            return value
    return title or artist


def _recursive_title(node: object, depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(node, str):
        value = _clean(node)
        return value if _valid_title(value) else ""
    if isinstance(node, list):
        for item in node:
            value = _recursive_title(item, depth + 1)
            if value:
                return value
        return ""
    if not isinstance(node, dict):
        return ""
    preferred = (
        "now_playing", "nowplaying", "currently_playing", "current_song",
        "current_track", "song", "track", "streamtitle", "stream_title",
        "title", "metadata", "data",
    )
    for key in preferred:
        if key in node:
            value = _song_from_node(node[key]) or _recursive_title(node[key], depth + 1)
            if _valid_title(value):
                return value
    for value in node.values():
        nested = _recursive_title(value, depth + 1)
        if nested:
            return nested
    return ""


def _source_title(source: dict[str, object]) -> str:
    return _recursive_title(source)


def _payload_title(payload: object) -> str:
    return _recursive_title(payload)


def _hcn_metadata_url(stream_url: str) -> str:
    parsed = urllib.parse.urlsplit(stream_url)
    if parsed.hostname and parsed.hostname.lower() == _HCN_HOST:
        match = _HCN_STREAM_PATTERN.search(parsed.path)
        if match:
            root = urllib.parse.urlunsplit((parsed.scheme or "https", parsed.netloc, "", "", ""))
            return f"{root}/api/meta?sid={match.group(1)}"
    return ""


def _fetch_json_title(endpoint: str, timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "SC-RTLT/1.3.6",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = decode_metadata_bytes(response.read(512_000), response.headers)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                value = _clean(raw)
                return True, value if _valid_title(value) else ""
            return True, _payload_title(payload)
    except Exception:
        return False, ""


def _generic_status_urls(stream_url: str) -> tuple[str, ...]:
    parsed = urllib.parse.urlsplit(stream_url)
    root = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    mount = parsed.path or "/"
    query = urllib.parse.urlencode({"mount": mount})
    return (
        f"{root}/status-json.xsl?{query}",
        f"{root}/status-json.xsl",
        f"{root}/stats-json.xsl?{query}",
    )


def _icy_metadata(stream_url: str, timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(
        stream_url,
        headers={
            "Icy-MetaData": "1",
            "Accept": "audio/mpeg,audio/aac,*/*",
            "User-Agent": "SC-RTLT/1.3.6",
            "Connection": "close",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            interval_text = response.headers.get("icy-metaint", "")
            try:
                interval = int(interval_text)
            except (TypeError, ValueError):
                interval = 0
            if interval <= 0 or interval > 2_000_000:
                return True, ""
            for _ in range(3):
                if len(_read_exact(response, interval)) != interval:
                    return True, ""
                length_byte = _read_exact(response, 1)
                if not length_byte:
                    return True, ""
                metadata_length = length_byte[0] * 16
                if metadata_length <= 0:
                    continue
                raw = decode_metadata_bytes(_read_exact(response, metadata_length), response.headers)
                match = _METADATA_PATTERN.search(raw)
                title = _clean(match.group(1).replace("''", "'") if match else raw)
                if _valid_title(title):
                    return True, title
            return True, ""
    except Exception:
        return False, ""


def _probe_hcn_in_parallel(stream_url: str, endpoint: str, timeout: float) -> tuple[bool, str]:
    """Probe HCN's JSON endpoint and ICY metadata concurrently.

    Some HCN relays expose the title through the JSON endpoint while others put
    it directly in the audio stream. Running both probes at the same time keeps
    the initial result bounded by one timeout instead of stacking several slow
    requests.
    """
    results: queue.Queue[tuple[bool, str]] = queue.Queue()

    def run(probe) -> None:
        try:
            results.put(probe())
        except Exception:
            results.put((False, ""))

    probes = (
        lambda: _fetch_json_title(endpoint, min(timeout, 2.0)),
        lambda: _icy_metadata(stream_url, timeout),
    )
    for index, probe in enumerate(probes):
        threading.Thread(
            target=run,
            args=(probe,),
            name=f"HCNMetadataSource{index + 1}",
            daemon=True,
        ).start()

    connected = False
    remaining = len(probes)
    deadline = time.monotonic() + max(0.5, timeout + 0.2)
    while remaining:
        wait = deadline - time.monotonic()
        if wait <= 0:
            break
        try:
            source_connected, title = results.get(timeout=wait)
        except queue.Empty:
            break
        remaining -= 1
        connected = connected or source_connected
        if title:
            return connected, title
    return connected, ""


def probe_stream_metadata(stream_url: str, timeout: float = 2.5) -> tuple[bool, str]:
    """Return ``(metadata_source_reached, current_title)`` quickly.

    HCN's dedicated JSON endpoint and the ICY metadata in the audio stream are
    queried in parallel. Therefore a dead source cannot postpone the first title
    by a chain of sequential timeouts.
    """
    url = _clean(stream_url)
    if not url:
        return False, ""
    if _is_tpr_stream(url):
        # The Streaming Pulse ICY field is decoded inconsistently by Windows/Qt
        # and by some relays. TPR already publishes the same track as proper
        # Unicode on its official site, so use that source exclusively. If the
        # site is temporarily unavailable, show no title rather than mojibake.
        return _fetch_tpr_title(max(6.0, timeout))
    if _is_recreg_stream(url):
        # REC·REG serves several stations from one Icecast host. Generic
        # status endpoints may return another mount's title, while each direct
        # MP3 mount exposes the correct UTF-8 StreamTitle through ICY.
        return _icy_metadata(url, timeout)
    hcn = _hcn_metadata_url(url)
    if hcn:
        return _probe_hcn_in_parallel(url, hcn, timeout)
    for endpoint in _generic_status_urls(url):
        connected, title = _fetch_json_title(endpoint, min(timeout, 1.0))
        if connected and title:
            return True, title
    return _icy_metadata(url, timeout)


class StreamMetadataPoller(QObject):
    metadata_found = Signal(str)
    status_changed = Signal(str)
    _probe_completed = Signal(int, bool, str)

    POLL_INTERVAL_MS = 3_000

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = ""
        self._active = False
        self._busy = False
        self._generation = 0
        self._last_connected: bool | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(self.POLL_INTERVAL_MS)
        self.timer.timeout.connect(self.probe_now)
        self._probe_completed.connect(self._finish_probe)

    @property
    def active_url(self) -> str:
        return self._url

    def start(self, stream_url: str) -> None:
        self._generation += 1
        self._url = _clean(stream_url)
        network_disabled = os.environ.get("SCWC_DISABLE_NETWORK", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self._active = bool(self._url) and not network_disabled
        self._busy = False
        self._last_connected = None
        self.timer.stop()
        if self._active:
            self.status_changed.emit("connecting")
            self.timer.start(self.POLL_INTERVAL_MS)
            QTimer.singleShot(0, self.probe_now)

    def pause(self) -> None:
        self._active = False
        self.timer.stop()
        self._generation += 1
        self.status_changed.emit("stopped")

    def stop(self) -> None:
        self.pause()
        self._url = ""
        self._busy = False

    def probe_now(self) -> None:
        if not self._active or not self._url or self._busy:
            return
        generation = self._generation
        url = self._url
        self._busy = True

        def worker() -> None:
            connected, title = probe_stream_metadata(url)
            self._probe_completed.emit(generation, connected, title)

        threading.Thread(target=worker, name="HCNMetadataProbe", daemon=True).start()

    def _finish_probe(self, generation: int, connected: bool, title: str) -> None:
        if generation != self._generation:
            return
        self._busy = False
        if not self._active:
            return
        if connected != self._last_connected:
            self.status_changed.emit("connected" if connected else "unavailable")
            self._last_connected = connected
        if title:
            self.status_changed.emit("title")
            self.metadata_found.emit(title)

    def shutdown(self) -> None:
        self.stop()
