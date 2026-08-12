from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Signal


GITHUB_REPOSITORY = "neehhhh/SC-RTLT"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
)
RELEASE_DOWNLOAD_PREFIX = f"/{GITHUB_REPOSITORY}/releases/download/"
MAX_RELEASE_RESPONSE_SIZE = 2 * 1024 * 1024
MAX_CHECKSUM_SIZE = 2 * 1024 * 1024
MAX_UPDATE_SIZE = 600 * 1024 * 1024
USER_AGENT = "SC-RTLT-Public-Updater"


class UpdateError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    asset: ReleaseAsset
    checksum_asset: ReleaseAsset | None = None


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    program: str
    arguments: tuple[str, ...]
    working_directory: str


def version_key(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", str(value or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_key = version_key(candidate)
    current_key = version_key(current)
    if not candidate_key or not current_key:
        return False
    width = max(len(candidate_key), len(current_key))
    return candidate_key + (0,) * (width - len(candidate_key)) > (
        current_key + (0,) * (width - len(current_key))
    )


def _validated_asset(payload: object) -> ReleaseAsset | None:
    if not isinstance(payload, dict):
        return None
    name = Path(str(payload.get("name") or "")).name.strip()
    download_url = str(payload.get("browser_download_url") or "").strip()
    parsed = urlparse(download_url)
    if (
        not name
        or parsed.scheme != "https"
        or parsed.netloc.casefold() != "github.com"
        or not parsed.path.casefold().startswith(RELEASE_DOWNLOAD_PREFIX.casefold())
    ):
        return None
    try:
        size = int(payload.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return ReleaseAsset(name=name, download_url=download_url, size=max(0, size))


def select_update_asset(assets: object) -> tuple[ReleaseAsset, ReleaseAsset | None]:
    valid_assets = [
        asset
        for asset in (_validated_asset(item) for item in (assets or []))
        if asset is not None
    ]
    checksum_asset = next(
        (
            asset
            for asset in valid_assets
            if asset.name.casefold()
            in {"sha256sums.txt", "sha256sum.txt", "checksums.txt"}
        ),
        None,
    )

    def score(asset: ReleaseAsset) -> int:
        name = asset.name.casefold()
        if name.endswith(".exe"):
            value = 130
        elif name.endswith(".zip"):
            value = 120
        else:
            return -1000
        if "windows" in name:
            value += 80
        if "setup" in name:
            value += 60
        if "sc-rtlt" in name or "sc_rtlt" in name:
            value += 50
        if "public" in name:
            value += 25
        if "portable" in name:
            value -= 30
        if "source" in name:
            value -= 200
        return value

    candidates = [asset for asset in valid_assets if score(asset) >= 0]
    if not candidates:
        raise UpdateError("no_asset")
    candidates.sort(key=lambda asset: (score(asset), asset.name.casefold()), reverse=True)
    return candidates[0], checksum_asset


def _request(url: str, *, accept: str = "application/vnd.github+json"):
    return urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )


def fetch_latest_release() -> ReleaseInfo:
    try:
        with urllib.request.urlopen(_request(LATEST_RELEASE_API), timeout=15) as response:
            raw = response.read(MAX_RELEASE_RESPONSE_SIZE + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("no_release") from exc
        if exc.code == 403:
            raise UpdateError("rate_limited") from exc
        raise UpdateError("network", f"GitHub HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("network", str(exc)) from exc
    if len(raw) > MAX_RELEASE_RESPONSE_SIZE:
        raise UpdateError("invalid_release")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("invalid_release") from exc
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise UpdateError("invalid_release")
    version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not version_key(version):
        raise UpdateError("invalid_release")
    asset, checksum_asset = select_update_asset(payload.get("assets"))
    return ReleaseInfo(
        version=version,
        asset=asset,
        checksum_asset=checksum_asset,
    )


def _download_small_text(asset: ReleaseAsset) -> str:
    if asset.size > MAX_CHECKSUM_SIZE:
        raise UpdateError("integrity")
    try:
        with urllib.request.urlopen(
            _request(asset.download_url, accept="application/octet-stream"),
            timeout=15,
        ) as response:
            raw = response.read(MAX_CHECKSUM_SIZE + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("integrity", str(exc)) from exc
    if len(raw) > MAX_CHECKSUM_SIZE:
        raise UpdateError("integrity")
    return raw.decode("utf-8", errors="replace")


def _expected_sha256(checksum_text: str, filename: str) -> str:
    target = Path(filename).name.casefold()
    for line in checksum_text.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]{64})\s+[* ]?(.+?)\s*$", line)
        if match and Path(match.group(2)).name.casefold() == target:
            return match.group(1).casefold()
    return ""


def download_release_asset(
    release: ReleaseInfo,
    *,
    progress_callback=None,
    interrupted_callback=None,
) -> Path:
    asset = release.asset
    if asset.size > MAX_UPDATE_SIZE:
        raise UpdateError("download_too_large")
    update_dir = Path(
        tempfile.mkdtemp(prefix=f"SC-RTLT_Public_Update_{version_key(release.version)[0]}_")
    )
    target = update_dir / Path(asset.name).name
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with urllib.request.urlopen(
            _request(asset.download_url, accept="application/octet-stream"),
            timeout=15,
        ) as response, target.open("wb") as output:
            header_size = response.headers.get("Content-Length", "")
            try:
                total = int(header_size)
            except (TypeError, ValueError):
                total = asset.size
            if total > MAX_UPDATE_SIZE:
                raise UpdateError("download_too_large")
            while True:
                if interrupted_callback is not None and interrupted_callback():
                    raise UpdateError("cancelled")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_UPDATE_SIZE:
                    raise UpdateError("download_too_large")
                output.write(chunk)
                digest.update(chunk)
                if progress_callback is not None and total > 0:
                    progress_callback(min(100, int(downloaded * 100 / total)))
        if asset.size and downloaded != asset.size:
            raise UpdateError("download_incomplete")
        if release.checksum_asset is not None:
            checksum_text = _download_small_text(release.checksum_asset)
            expected = _expected_sha256(checksum_text, asset.name)
            if not expected or digest.hexdigest().casefold() != expected:
                raise UpdateError("integrity")
        return target
    except UpdateError:
        shutil.rmtree(update_dir, ignore_errors=True)
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        shutil.rmtree(update_dir, ignore_errors=True)
        raise UpdateError("download", str(exc)) from exc
    except Exception:
        shutil.rmtree(update_dir, ignore_errors=True)
        raise


def _safe_extract_zip(archive: Path) -> Path:
    destination = archive.parent / "payload"
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            total_size = 0
            for item in bundle.infolist():
                total_size += max(0, int(item.file_size))
                if total_size > MAX_UPDATE_SIZE * 2:
                    raise UpdateError("invalid_package")
                target = (root / item.filename).resolve()
                if target != root and root not in target.parents:
                    raise UpdateError("invalid_package")
            bundle.extractall(root)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError("invalid_package", str(exc)) from exc
    return destination


def prepare_downloaded_update(release: ReleaseInfo, archive: Path) -> PreparedUpdate:
    suffix = archive.suffix.casefold()
    if suffix == ".exe":
        return PreparedUpdate(
            version=release.version,
            program=str(archive),
            arguments=(),
            working_directory=str(archive.parent),
        )
    if suffix != ".zip":
        raise UpdateError("invalid_package")
    destination = _safe_extract_zip(archive)
    install_scripts = sorted(
        (
            path
            for path in destination.rglob("install.ps1")
            if path.parent.name.casefold() == "windows"
            and path.parent.parent.name.casefold() == "tools"
        ),
        key=lambda path: (len(path.parts), str(path).casefold()),
    )
    if install_scripts:
        script = install_scripts[0]
        return PreparedUpdate(
            version=release.version,
            program="powershell.exe",
            arguments=(
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-AutomaticUpdate",
            ),
            working_directory=str(script.parent.parent.parent),
        )
    setup_files = sorted(
        (
            path
            for path in destination.rglob("*")
            if path.is_file() and path.name.casefold() == "setup.bat"
        ),
        key=lambda path: (len(path.parts), str(path).casefold()),
    )
    if not setup_files:
        raise UpdateError("invalid_package")
    setup = setup_files[0]
    return PreparedUpdate(
        version=release.version,
        program="cmd.exe",
        arguments=("/d", "/c", str(setup), "-AutomaticUpdate"),
        working_directory=str(setup.parent),
    )


def launch_prepared_update(update: PreparedUpdate) -> None:
    if os.name != "nt":
        raise UpdateError("platform")
    flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            [update.program, *update.arguments],
            cwd=update.working_directory,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        raise UpdateError("launch", str(exc)) from exc


_ACTIVE_WORKERS: set["UpdateWorker"] = set()


def retain_worker(worker: "UpdateWorker") -> None:
    _ACTIVE_WORKERS.add(worker)
    worker.finished.connect(lambda: _ACTIVE_WORKERS.discard(worker))


class UpdateWorker(QThread):
    checking = Signal()
    download_progress = Signal(int)
    up_to_date = Signal(str)
    update_ready = Signal(object)
    failed = Signal(str, str)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = current_version

    def run(self) -> None:
        try:
            self.checking.emit()
            release = fetch_latest_release()
            if not is_newer_version(release.version, self.current_version):
                self.up_to_date.emit(release.version)
                return
            archive = download_release_asset(
                release,
                progress_callback=self.download_progress.emit,
                interrupted_callback=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                return
            prepared = prepare_downloaded_update(release, archive)
            self.update_ready.emit(prepared)
        except UpdateError as exc:
            if exc.code != "cancelled":
                self.failed.emit(exc.code, exc.detail)
        except Exception as exc:  # Defensive boundary for the background thread.
            self.failed.emit("unknown", f"{type(exc).__name__}: {exc}")
