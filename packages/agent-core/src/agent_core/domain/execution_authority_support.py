from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_UNSAFE_MARKERS = (
    "bearer ",
    "access_token",
    "refresh_token",
    "client_secret",
    "password=",
    "secret=",
    "credential=",
)


def normalize_digest(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized.removeprefix("sha256:")


def reject_secret_material(value: str) -> None:
    lowered = value.casefold()
    if any(marker in lowered for marker in _UNSAFE_MARKERS):
        raise ValueError("authority metadata must not contain credential material")


def digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
