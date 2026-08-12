from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

from PySide6.QtCore import QObject, QSettings, QTimer, Signal


_INVENTORY_OPEN_RE = re.compile(
    rb"(?:"
    rb"Caller\[CSCLocalPlayerPersonalThoughtComponent::RequestInventoryData\]"
    rb"|\bPlayerInventoryRequest\b"
    rb")",
    re.IGNORECASE,
)
_INVENTORY_CLOSE_RE = re.compile(
    rb"(?:"
    rb"<Close Inventory Grid>"
    rb"|<Request Terminate Access To Inventory>"
    rb"|<Remove Inventory Container UI>"
    rb")",
    re.IGNORECASE,
)
_ASOP_OPEN_RE = re.compile(
    rb"<OnRequestFetchVehicles>\s+Fetching player vehicle list",
    re.IGNORECASE,
)
_LOADING_OPEN_RE = re.compile(
    rb"(?:\[|<)CGlobalGameUI::OpenLoadingScreen(?:\]|>)",
    re.IGNORECASE,
)
_LOADING_CLOSE_RE = re.compile(rb"Loading screen for .+ closed after", re.IGNORECASE)
_PLAYER_SPAWNED_RE = re.compile(
    rb"\[CSessionManager::OnClientSpawned\]\s+Spawned!",
    re.IGNORECASE,
)

_CHANNELS = ("LIVE", "PTU", "EPTU", "TECH-PREVIEW")
_MAX_READ_BYTES = 256 * 1024
_MAX_LINE_BYTES = 1024 * 1024
_CURSOR_SHOWING = 0x00000001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_VK_I = 0x49
_VK_ESCAPE = 0x1B
_VK_F2 = 0x71
_VK_B = 0x42


@dataclass(frozen=True, slots=True)
class GameUiLogEvent:
    kind: str
    active: bool
    transient_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class WindowsGameUiProbeState:
    game_foreground: bool
    cursor_showing: bool
    process_name: str = ""
    inventory_key_down: bool = False
    escape_key_down: bool = False
    f2_key_down: bool = False
    quantum_key_down: bool = False


def should_hide_widget_for_game_ui(active: bool, reason: str = "") -> bool:
    """Only an active inventory is allowed to hide the normal widget."""
    return bool(active) and str(reason or "").strip().casefold() == "inventory"


class GameUiLogParser:
    """Extract only high-confidence UI transitions from Star Citizen's Game.log."""

    def parse_line(self, line: bytes | str) -> GameUiLogEvent | None:
        payload = line.encode("utf-8", errors="replace") if isinstance(line, str) else line
        if len(payload) > _MAX_LINE_BYTES:
            return None
        if _INVENTORY_CLOSE_RE.search(payload):
            return GameUiLogEvent("inventory", False)
        if _PLAYER_SPAWNED_RE.search(payload):
            return GameUiLogEvent("player_spawned", True)
        if _INVENTORY_OPEN_RE.search(payload):
            return GameUiLogEvent("inventory", True)
        if _ASOP_OPEN_RE.search(payload):
            return GameUiLogEvent("asop", True, transient_seconds=120.0)
        if _LOADING_CLOSE_RE.search(payload):
            return GameUiLogEvent("loading", False)
        if _LOADING_OPEN_RE.search(payload):
            return GameUiLogEvent("loading", True)
        return None


class WindowsGameUiProbe:
    """Read ordinary Win32 window/cursor state without hooks or process injection."""

    def __init__(self) -> None:
        self._available = os.name == "nt"
        self._user32 = None
        self._kernel32 = None
        self._cursor_info_type = None
        if self._available:
            self._configure()

    def _configure(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            class CursorInfo(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hCursor", wintypes.HCURSOR),
                    ("ptScreenPos", wintypes.POINT),
                ]

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.GetCursorInfo.argtypes = [ctypes.POINTER(CursorInfo)]
            user32.GetCursorInfo.restype = wintypes.BOOL
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short

            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            self._user32 = user32
            self._kernel32 = kernel32
            self._cursor_info_type = CursorInfo
        except (AttributeError, OSError, TypeError):
            self._available = False

    def sample(self) -> WindowsGameUiProbeState:
        if not self._available or self._user32 is None or self._kernel32 is None:
            return WindowsGameUiProbeState(False, False, "", False, False, False, False)
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return WindowsGameUiProbeState(False, False, "", False, False, False, False)
            process_id = wintypes.DWORD(0)
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            process_name = self._process_name(int(process_id.value))
            window_title = self._window_title(hwnd)
            # EAC or Windows integrity boundaries can prevent QueryFullProcessImageNameW
            # even while the Star Citizen window is unquestionably foreground. The
            # ordinary top-level title is a safe read-only fallback for keys/cursor.
            is_game = (
                process_name.casefold() == "starcitizen.exe"
                or "star citizen" in window_title.casefold()
            )

            cursor_showing = False
            if is_game and self._cursor_info_type is not None:
                info = self._cursor_info_type()
                info.cbSize = ctypes.sizeof(self._cursor_info_type)
                if self._user32.GetCursorInfo(ctypes.byref(info)):
                    cursor_showing = bool(int(info.flags) & _CURSOR_SHOWING)
            inventory_key_down = False
            escape_key_down = False
            f2_key_down = False
            quantum_key_down = False
            if is_game:
                # High bit = currently held; low bit = pressed since the previous
                # call. Reading both avoids missing a quick tap between 120 ms polls.
                inventory_key_down = bool(int(self._user32.GetAsyncKeyState(_VK_I)) & 0x8001)
                escape_key_down = bool(int(self._user32.GetAsyncKeyState(_VK_ESCAPE)) & 0x8001)
                f2_key_down = bool(int(self._user32.GetAsyncKeyState(_VK_F2)) & 0x8001)
                quantum_key_down = bool(int(self._user32.GetAsyncKeyState(_VK_B)) & 0x8001)
            return WindowsGameUiProbeState(
                is_game,
                cursor_showing,
                process_name or window_title,
                inventory_key_down,
                escape_key_down,
                f2_key_down,
                quantum_key_down,
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return WindowsGameUiProbeState(False, False, "", False, False, False, False)

    def _window_title(self, hwnd) -> str:
        if not hwnd or self._user32 is None:
            return ""
        try:
            import ctypes

            length = int(self._user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return ""
            buffer = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(hwnd, buffer, length + 1)
            return str(buffer.value or "")
        except (AttributeError, OSError, TypeError, ValueError):
            return ""

    def _process_name(self, process_id: int) -> str:
        if process_id <= 0 or self._kernel32 is None:
            return ""
        try:
            import ctypes
            from ctypes import wintypes

            handle = self._kernel32.OpenProcess(
                _PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
            )
            if not handle:
                return ""
            try:
                size = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(int(size.value))
                if not self._kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)
                ):
                    return ""
                return Path(buffer.value).name
            finally:
                self._kernel32.CloseHandle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            return ""


class GameUiStateMonitor(QObject):
    """Hide the companion widget while a Star Citizen UI is actively in use."""

    ui_active_changed = Signal(bool, str)
    location_refresh_requested = Signal(str)
    quantum_commit_requested = Signal()

    def __init__(
        self,
        settings: QSettings,
        parent: QObject | None = None,
        *,
        probe: Callable[[], WindowsGameUiProbeState] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        native_probe = WindowsGameUiProbe()
        self._probe = probe or native_probe.sample
        self._clock = clock
        self.parser = GameUiLogParser()
        self.timer = QTimer(self)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self.poll)

        self._file: BinaryIO | None = None
        self._path: Path | None = None
        self._position = 0
        self._partial = b""
        self._last_identity: tuple[int, int] | None = None
        self._path_probe_counter = 0

        self._inventory_active = False
        self._loading_active = False
        self._transient_kind = ""
        self._transient_until = 0.0
        self._last_log_activity_at = 0.0

        self._cursor_calibrated = False
        self._cursor_ui_active = False
        self._cursor_show_polls = 0
        self._cursor_hide_polls = 0
        self._ui_active = False
        self._last_reason = ""
        self._inventory_key_was_down = False
        self._escape_key_was_down = False
        self._f2_key_was_down = False
        self._quantum_key_hold_polls = 0
        self._quantum_key_emitted = False
        self._inventory_key_pending_until = 0.0
        self._inventory_open_confirmed_by_log = False
        self._inventory_log_revision = 0
        self._last_location_refresh_at = -999.0

    @property
    def inventory_enabled(self) -> bool:
        return self.settings.value("widget/hide_in_inventory_enabled", True, type=bool)

    @property
    def location_hotkeys_enabled(self) -> bool:
        return self.settings.value("game_log/auto_location_enabled", True, type=bool)

    @property
    def enabled(self) -> bool:
        # Escape/F2 location restoration must keep working even when the user has
        # disabled the generic UI-hiding feature.
        return self.inventory_enabled or self.location_hotkeys_enabled

    @property
    def ui_active(self) -> bool:
        return self._ui_active

    @property
    def active_reason(self) -> str:
        return self._last_reason

    def start(self) -> None:
        if not self.enabled:
            self._emit(False, "")
            return
        if not self.timer.isActive():
            self.timer.start()
        self._open_latest_log_at_end()
        self.poll()

    def reconfigure(self) -> None:
        if not self.enabled:
            self.stop()
            self._emit(False, "")
            return
        self._close_file()
        self._reset_runtime_state()
        self.start()

    def stop(self) -> None:
        self.timer.stop()
        self._close_file()
        self._reset_runtime_state()
        self._emit(False, "")

    shutdown = stop

    def poll(self) -> None:
        if not self.enabled:
            self.stop()
            return
        inventory_log_revision = self._inventory_log_revision
        self._poll_log()
        inventory_log_event_seen = self._inventory_log_revision != inventory_log_revision
        now = self._clock()
        sample = self._probe()

        if not sample.game_foreground:
            self._cursor_show_polls = 0
            self._cursor_hide_polls = 0
            self._cursor_ui_active = False
            self._inventory_key_was_down = False
            self._escape_key_was_down = False
            self._f2_key_was_down = False
            self._quantum_key_hold_polls = 0
            self._quantum_key_emitted = False
            # A high-confidence Game.log inventory event must not be cancelled by
            # a failed foreground-process probe. This was the 1.0.9 inventory bug.
            if self._inventory_active and self._inventory_open_confirmed_by_log:
                self._emit(True, "inventory")
            else:
                self._emit(False, "")
            return

        inventory_key_pressed = bool(
            sample.inventory_key_down and not self._inventory_key_was_down
        )
        escape_key_pressed = bool(sample.escape_key_down and not self._escape_key_was_down)
        f2_key_pressed = bool(sample.f2_key_down and not self._f2_key_was_down)
        self._inventory_key_was_down = bool(sample.inventory_key_down)
        self._escape_key_was_down = bool(sample.escape_key_down)
        self._f2_key_was_down = bool(sample.f2_key_down)

        # Star Citizen 4.9 does not always log a dedicated QT-start event
        # when already outside monitored space. A sustained default B press is a
        # read-only fallback. Requiring three polls avoids ordinary chat typing.
        if sample.quantum_key_down and not sample.cursor_showing:
            self._quantum_key_hold_polls += 1
            if self._quantum_key_hold_polls >= 3 and not self._quantum_key_emitted:
                self._quantum_key_emitted = True
                self.quantum_commit_requested.emit()
        else:
            self._quantum_key_hold_polls = 0
            self._quantum_key_emitted = False

        if escape_key_pressed or f2_key_pressed:
            self._inventory_active = False
            self._inventory_key_pending_until = 0.0
            self._inventory_open_confirmed_by_log = False
            self._request_location_refresh("f2" if f2_key_pressed else "escape")
        elif (
            inventory_key_pressed
            and not inventory_log_event_seen
            and self.inventory_enabled
            and not self._loading_active
        ):
            # Read-only fallback for 4.9 sessions where the opening log line is
            # delayed or omitted. No keyboard hook or game-process injection is used.
            self._inventory_active = not self._inventory_active
            self._inventory_open_confirmed_by_log = False
            self._inventory_key_pending_until = now + 2.0 if self._inventory_active else 0.0
            self._last_log_activity_at = now

        cursor_ui_was_active = self._cursor_ui_active
        if sample.cursor_showing:
            self._cursor_hide_polls = 0
            if self._cursor_calibrated:
                self._cursor_show_polls += 1
                if self._cursor_show_polls >= 2:
                    self._cursor_ui_active = True
        else:
            self._cursor_calibrated = True
            self._cursor_show_polls = 0
            self._cursor_hide_polls += 1
            if self._cursor_hide_polls >= 3:
                self._cursor_ui_active = False
                # A stable hidden cursor means normal gameplay. Transient
                # terminal hints may be cleared, while exact inventory/loading
                # states remain active until their matching close event.
                self._transient_kind = ""
                self._transient_until = 0.0

        # Map closure must not depend on the generic UI-hide setting. When the
        # mobiGlas cursor was stably visible and becomes stably hidden, ask the
        # location parser to end a temporary Starmap preview. The parser itself
        # ignores this request when no preview is active, so inventory/ASOP closes
        # cannot disturb an engaged QT destination.
        if cursor_ui_was_active and not self._cursor_ui_active and not self._loading_active:
            self._request_location_refresh("ui_closed")

        if self._transient_until and now >= self._transient_until:
            self._transient_kind = ""
            self._transient_until = 0.0

        # A keyboard-only opening is accepted when the inventory cursor appears.
        # Otherwise cancel it quickly to avoid hiding after typing the letter I in chat.
        if self._inventory_key_pending_until:
            if sample.cursor_showing:
                self._inventory_key_pending_until = 0.0
            elif now >= self._inventory_key_pending_until:
                if not self._inventory_open_confirmed_by_log:
                    self._inventory_active = False
                self._inventory_key_pending_until = 0.0

        # Never allow an unmatched log event to keep the widget hidden forever.
        if self._last_log_activity_at and now - self._last_log_activity_at > 600.0:
            self._inventory_active = False
            self._loading_active = False
            self._transient_kind = ""
            self._transient_until = 0.0

        if self._inventory_active and self.inventory_enabled:
            self._emit(True, "inventory")
        else:
            self._emit(False, "")

    def process_log_line(self, line: bytes | str) -> None:
        event = self.parser.parse_line(line)
        if event is None:
            return
        now = self._clock()
        self._last_log_activity_at = now
        if event.kind == "player_spawned":
            # During a respawn Star Citizen rebuilds the player's attachments
            # and emits several RequestInventoryData lines immediately before
            # OnClientSpawned. Those requests are not an opened inventory and
            # never receive a matching close event.
            self._inventory_active = False
            self._inventory_open_confirmed_by_log = False
            self._inventory_key_pending_until = 0.0
            self._loading_active = False
        elif event.kind == "loading":
            self._loading_active = event.active
            if event.active:
                # Star Citizen requests inventory data during player spawning.
                # It is not an inventory screen and has no matching close line.
                self._inventory_active = False
                self._inventory_open_confirmed_by_log = False
                self._inventory_key_pending_until = 0.0
        elif event.kind == "inventory":
            self._inventory_log_revision += 1
            if event.active and self._loading_active:
                return
            self._inventory_active = event.active
            self._inventory_open_confirmed_by_log = event.active
            self._inventory_key_pending_until = 0.0
        elif event.active and event.transient_seconds > 0:
            self._transient_kind = event.kind
            self._transient_until = now + event.transient_seconds

    def _poll_log(self) -> None:
        if self._file is None or self._path is None:
            self._path_probe_counter += 1
            if self._path_probe_counter == 1 or self._path_probe_counter % 10 == 0:
                self._open_latest_log_at_end()
            return
        try:
            stat = self._path.stat()
        except OSError:
            self._close_file()
            return
        identity = (int(getattr(stat, "st_dev", 0)), int(getattr(stat, "st_ino", 0)))
        if stat.st_size < self._position or (
            self._last_identity is not None and identity != self._last_identity
        ):
            self._open_path_at_end(self._path)
            return
        self._last_identity = identity
        try:
            self._file.seek(self._position)
            chunk = self._file.read(_MAX_READ_BYTES)
        except OSError:
            self._close_file()
            return
        if not chunk:
            return
        self._position += len(chunk)
        self._consume(chunk)

    def _consume(self, chunk: bytes) -> None:
        data = self._partial + chunk
        lines = data.splitlines(keepends=True)
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            self._partial = lines.pop()
            if len(self._partial) > _MAX_LINE_BYTES:
                self._partial = b""
        else:
            self._partial = b""
        for line in lines:
            self.process_log_line(line)

    def _open_latest_log_at_end(self) -> None:
        selected = self._select_existing_path(self.candidate_paths())
        if selected is None:
            self._close_file()
            return
        self._open_path_at_end(selected)

    def _open_path_at_end(self, path: Path) -> None:
        self._close_file()
        try:
            handle = path.open("rb")
            stat = path.stat()
            handle.seek(stat.st_size)
        except OSError:
            return
        self._file = handle
        self._path = path
        self._position = stat.st_size
        self._partial = b""
        self._last_identity = (int(getattr(stat, "st_dev", 0)), int(getattr(stat, "st_ino", 0)))
        self._path_probe_counter = 0

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

    def _reset_runtime_state(self) -> None:
        self._inventory_active = False
        self._loading_active = False
        self._transient_kind = ""
        self._transient_until = 0.0
        self._last_log_activity_at = 0.0
        self._cursor_calibrated = False
        self._cursor_ui_active = False
        self._cursor_show_polls = 0
        self._cursor_hide_polls = 0
        self._inventory_key_was_down = False
        self._escape_key_was_down = False
        self._f2_key_was_down = False
        self._quantum_key_hold_polls = 0
        self._quantum_key_emitted = False
        self._inventory_key_pending_until = 0.0
        self._inventory_open_confirmed_by_log = False
        self._last_location_refresh_at = -999.0

    def _request_location_refresh(self, reason: str) -> None:
        now = self._clock()
        if reason == "ui_closed" and now - self._last_location_refresh_at < 0.1:
            return
        self._last_location_refresh_at = now
        self.location_refresh_requested.emit(str(reason or "physical"))

    def _emit(self, active: bool, reason: str) -> None:
        active = bool(active)
        reason = str(reason or "") if active else ""
        if active == self._ui_active and reason == self._last_reason:
            return
        self._ui_active = active
        self._last_reason = reason
        self.ui_active_changed.emit(active, reason)

    def candidate_paths(self) -> tuple[Path, ...]:
        candidates: list[Path] = []
        configured = self.settings.value("game_log/path", "", type=str).strip()
        if configured:
            path = Path(configured).expanduser()
            candidates.append(path / "Game.log" if path.is_dir() else path)
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
