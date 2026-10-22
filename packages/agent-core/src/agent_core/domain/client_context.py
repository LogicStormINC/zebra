"""Client state snapshot domain model (ADR-CLIENT-01).

The snapshot is an interaction projection of what the mounted page
declared — never a business fact source. Values ride the durable
command payload; only sanitized references reach worker context.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_CLIENT_STATE_BYTES = 65_536
REDACTED_SENTINEL = "__redacted__"
SENSITIVE_KEY_TOKENS = ("secret", "token", "password", "cookie", "authorization")


class ClientStateError(ValueError):
    pass


class ClientStateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    client_session_id: str = Field(min_length=1)
    frontend_app_id: str | None = None
    profile_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ui_revision: int = Field(default=0, ge=0)
    state: dict[str, Any] = Field(default_factory=dict)
    redacted_keys: tuple[str, ...] = ()

    @property
    def state_digest(self) -> str:
        encoded = json.dumps(
            self.state, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def state_bytes(self) -> int:
        encoded = json.dumps(
            self.state, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return len(encoded)


def validate_client_state_json(state: object) -> None:
    """Bound raw JSON before coercion, redaction or recursive schema work."""
    if not isinstance(state, dict):
        raise ClientStateError("client state must be a JSON object")
    stack: list[tuple[Any, int]] = [(state, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 32 or count + len(stack) > 4096:
            raise ClientStateError("client state exceeds its structural budget")
        if isinstance(item, dict | list) and len(item) > 4096 - count - len(stack):
            raise ClientStateError("client state exceeds its structural budget")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ClientStateError("client state keys must be strings")
            for key in item:
                _validate_client_text(key)
            stack.extend((value, depth + 1) for value in item.values())
        elif isinstance(item, list):
            stack.extend((value, depth + 1) for value in item)
        elif isinstance(item, str):
            _validate_client_text(item)
        elif type(item) not in (int, float, bool, type(None)):
            raise ClientStateError("client state must contain JSON values")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ClientStateError("client state numbers must be finite")
    if (
        len(json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        > MAX_CLIENT_STATE_BYTES
    ):
        raise ClientStateError("client state exceeds its byte budget")


def _validate_client_text(value: str) -> None:
    if "\x00" in value:
        raise ClientStateError("client state text must not contain NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ClientStateError("client state text must be valid UTF-8 scalars") from exc


def sanitize_client_state(state: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Deep-redact sensitive keys; the raw payload never persists."""

    redacted: list[str] = []

    def _walk(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            walked: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in SENSITIVE_KEY_TOKENS):
                    redacted.append(f"{path}{key}")
                    walked[str(key)] = REDACTED_SENTINEL
                else:
                    walked[str(key)] = _walk(item, f"{path}{key}.")
            return walked
        if isinstance(value, list):
            return [_walk(item, path) for item in value]
        return value

    return _walk(state, ""), tuple(sorted(set(redacted)))


def validate_client_state_snapshot(snapshot: ClientStateSnapshot) -> None:
    """Enforce the byte budget and reject unsanitized sensitive keys."""

    if snapshot.state_bytes > MAX_CLIENT_STATE_BYTES:
        raise ClientStateError(f"client state snapshot exceeds {MAX_CLIENT_STATE_BYTES} bytes")
    sanitized, sensitive = sanitize_client_state(snapshot.state)
    if sanitized != snapshot.state:
        raise ClientStateError(
            f"client state carries unsanitized sensitive keys: {list(sensitive)[:8]}"
        )
