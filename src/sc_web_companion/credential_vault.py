from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import config_directory


@dataclass(frozen=True, slots=True)
class SavedCredential:
    origin: str
    username: str
    password: str


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, object]:
    buffer = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("Le coffre de mots de passe est disponible uniquement sous Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(b"PublicRealTimeChecker-v1")
    output = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        ctypes.c_wchar_p("Public Real Time Checker"),
        ctypes.byref(entropy),
        None,
        None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(output),
    )
    del source_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("Le coffre de mots de passe est disponible uniquement sous Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(b"PublicRealTimeChecker-v1")
    output = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        0x01,
        ctypes.byref(output),
    )
    del source_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


class CredentialVault:
    """Small opt-in vault protected by Windows DPAPI for the current user."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_directory() / "credentials.json")

    @property
    def available(self) -> bool:
        return os.name == "nt"

    @staticmethod
    def _normalise_origin(origin: str) -> str:
        return str(origin or "").strip().lower().rstrip("/")

    def _read(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _write(self, payload: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(self, origin: str, username: str, password: str) -> None:
        origin = self._normalise_origin(origin)
        if not origin or not password:
            raise ValueError("Origine et mot de passe requis.")
        if not self.available:
            raise OSError("Le coffre Windows est indisponible.")
        secret = json.dumps({"username": username, "password": password}, ensure_ascii=False).encode("utf-8")
        payload = self._read()
        payload[origin] = {
            "version": "1",
            "protected": base64.b64encode(_dpapi_protect(secret)).decode("ascii"),
        }
        self._write(payload)

    def get(self, origin: str) -> SavedCredential | None:
        origin = self._normalise_origin(origin)
        node = self._read().get(origin)
        if not origin or not node or not self.available:
            return None
        try:
            protected = base64.b64decode(node["protected"], validate=True)
            decoded = json.loads(_dpapi_unprotect(protected).decode("utf-8"))
            return SavedCredential(origin, str(decoded.get("username", "")), str(decoded.get("password", "")))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def delete(self, origin: str) -> bool:
        origin = self._normalise_origin(origin)
        payload = self._read()
        existed = origin in payload
        payload.pop(origin, None)
        if existed:
            self._write(payload)
        return existed

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def export_safe_index(self) -> list[dict[str, str]]:
        return [{"origin": origin} for origin in sorted(self._read())]
