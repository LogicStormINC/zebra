"""Client state snapshot domain model (ADR-CLIENT-01).

The snapshot is an interaction projection of what the mounted page
declared — never a business fact source. Values ride the durable
command payload; only sanitized references reach worker context.
"""

from __future__ import annotations

import hashlib
import json
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
        raise ClientStateError(
            f"client state snapshot exceeds {MAX_CLIENT_STATE_BYTES} bytes"
        )
    _, still_sensitive = sanitize_client_state(snapshot.state)
    if still_sensitive:
        raise ClientStateError(
            "client state carries unsanitized sensitive keys:"
            f" {list(still_sensitive)[:8]}"
        )
