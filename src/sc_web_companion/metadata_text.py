from __future__ import annotations

import re
from email.message import Message

_REPLACEMENT_CHARACTER = "\ufffd"
_MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "â€",
    "â€™",
    "â€œ",
    "â€\u009d",
    "â€“",
    "â€”",
    "ðŸ",
    "ï»¿",
    # UTF-8 decoded as Windows-1252/Latin-1 for non-Western scripts.
    # These sequences are commonly perceived as Greek or Cyrillic glyphs.
    "Î",
    "Ï",
    "Ð",
    "Ñ",
    "Ø",
    "Ù",
    "Ú",
)
_CHARSET_PATTERN = re.compile(r"charset\s*=\s*[\"']?([^;\s\"']+)", re.IGNORECASE)


def _text_penalty(value: str) -> int:
    penalty = value.count(_REPLACEMENT_CHARACTER) * 100
    penalty += sum(20 for char in value if (ord(char) < 32 and char not in "\t\r\n") or 0x7F <= ord(char) <= 0x9F)
    penalty += sum(value.count(marker) * 8 for marker in _MOJIBAKE_MARKERS)
    return penalty


def _declared_charset(headers_or_content_type: object | None) -> str:
    if headers_or_content_type is None:
        return ""
    if isinstance(headers_or_content_type, Message):
        try:
            return str(headers_or_content_type.get_content_charset() or "").strip()
        except Exception:
            return ""
    try:
        content_type = str(headers_or_content_type.get("content-type", ""))
    except Exception:
        content_type = str(headers_or_content_type or "")
    match = _CHARSET_PATTERN.search(content_type)
    return match.group(1).strip() if match else ""


def decode_metadata_bytes(raw: bytes | bytearray, headers_or_content_type: object | None = None) -> str:
    """Decode ICY/JSON metadata without corrupting valid UTF-8.

    Some Shoutcast relays announce ISO-8859-1 or Windows-1252 while their ICY
    title is actually UTF-8. Therefore strict UTF-8 must win whenever the byte
    sequence is valid. The announced charset is only a fallback after UTF-8,
    followed by Windows-1252 and lossless Latin-1.
    """
    data = bytes(raw or b"").rstrip(b"\x00")
    if not data:
        return ""

    declared = _declared_charset(headers_or_content_type)
    encodings: list[str] = []
    if data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        encodings.extend(("utf-8-sig", "utf-16"))

    # This order is intentional. A misleading server declaration must never
    # turn valid UTF-8 into mojibake such as "Î£Ï„...".
    encodings.append("utf-8")
    if declared:
        encodings.append(declared)
    encodings.extend(("cp1252", "latin-1"))

    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for order, encoding in enumerate(encodings):
        key = encoding.casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            text = data.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
        candidates.append((_text_penalty(text), order, text))

    if not candidates:
        return data.decode("latin-1", errors="strict")
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _repair_utf8_mojibake(value: str) -> str:
    """Undo reversible UTF-8-as-legacy decoding passes.

    A conversion is accepted only when it is lossless and lowers the
    mojibake/control-character score. Correct Unicode, including genuine Greek
    or Cyrillic text, therefore remains untouched.
    """
    current = value
    for _ in range(3):
        current_penalty = _text_penalty(current)
        best = current
        best_penalty = current_penalty
        for source_encoding in ("cp1252", "latin-1"):
            try:
                candidate = current.encode(source_encoding, errors="strict").decode("utf-8", errors="strict")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            candidate_penalty = _text_penalty(candidate)
            if candidate_penalty < best_penalty:
                best = candidate
                best_penalty = candidate_penalty
        if best == current:
            break
        current = best
    return current


def clean_metadata_text(value: object) -> str:
    """Normalize metadata and reject text already destroyed by a decoder."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(
            part for part in (clean_metadata_text(item) for item in value) if part
        )
    text = str(value).replace("\x00", "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    if _REPLACEMENT_CHARACTER in text:
        # Once U+FFFD exists, the source byte is gone. Suppress this native Qt
        # value and let the raw ICY poller provide a recoverable title.
        return ""
    text = _repair_utf8_mojibake(text)
    return " ".join(text.split())
