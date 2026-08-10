from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId

MAX_COMMAND_PAYLOAD_BYTES = 64 * 1024
MAX_IDEMPOTENCY_KEY_LENGTH = 256


class SessionCommandKind(StrEnum):
    RUN = "run"
    RESUME = "resume"
    MESSAGE = "message"
    STOP = "stop"
    CANCEL = "cancel"
    SUSPEND = "suspend"


class SessionCommandStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    REVISION_CONFLICT = "revision_conflict"


class SessionCommand(BaseModel):
    """Provider-neutral intent submitted to a durable session command seam."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(default_factory=uuid4)
    session_id: SessionId
    kind: SessionCommandKind
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be blank")
        return normalized

    @field_validator("payload")
    @classmethod
    def validate_json_payload(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("command payload must be JSON serializable") from exc
        if len(encoded) > MAX_COMMAND_PAYLOAD_BYTES:
            raise ValueError("command payload is too large")
        return dict(value)

    @model_validator(mode="after")
    def validate_kind_payload(self) -> SessionCommand:
        if self.kind is SessionCommandKind.MESSAGE:
            content = self.payload.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("message command requires non-blank payload.content")
        if self.kind is SessionCommandKind.RESUME:
            worker_id = self.payload.get("worker_id")
            if worker_id is not None and (
                not isinstance(worker_id, str) or not worker_id.strip()
            ):
                raise ValueError("resume payload.worker_id must be non-blank when provided")
            lease_ttl = self.payload.get("lease_ttl_seconds")
            if lease_ttl is not None and (
                not isinstance(lease_ttl, int) or isinstance(lease_ttl, bool) or lease_ttl <= 0
            ):
                raise ValueError("resume payload.lease_ttl_seconds must be positive")
        return self

    @property
    def fingerprint(self) -> str:
        intent = {
            "session_id": str(self.session_id),
            "kind": self.kind.value,
            "expected_revision": self.expected_revision,
            "payload": self.payload,
        }
        encoded = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def event_payload(self) -> dict[str, object]:
        return SessionCommandAcceptedPayload(
            command_id=self.command_id,
            session_id=self.session_id,
            kind=self.kind,
            expected_revision=self.expected_revision,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            fingerprint=self.fingerprint,
        ).model_dump(mode="json")


class SessionCommandAcceptedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    session_id: UUID
    kind: SessionCommandKind
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
    payload: dict[str, object]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class SessionCommandDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: SessionCommandStatus
    event_type: EventType | None = None
    reason: str | None = None
    current_revision: int = Field(ge=0)


def decide_session_command(
    command: SessionCommand,
    *,
    current_revision: int,
    existing_fingerprint: str | None = None,
) -> SessionCommandDecision:
    """Apply idempotency before optimistic revision admission."""
    if current_revision < 0:
        raise ValueError("current_revision must not be negative")
    if existing_fingerprint is not None:
        if existing_fingerprint == command.fingerprint:
            return SessionCommandDecision(
                status=SessionCommandStatus.DUPLICATE,
                current_revision=current_revision,
            )
        return SessionCommandDecision(
            status=SessionCommandStatus.IDEMPOTENCY_CONFLICT,
            reason="idempotency key reused with different command",
            current_revision=current_revision,
        )
    if command.expected_revision != current_revision:
        return SessionCommandDecision(
            status=SessionCommandStatus.REVISION_CONFLICT,
            reason=(
                f"expected revision {command.expected_revision}, "
                f"current revision {current_revision}"
            ),
            current_revision=current_revision,
        )
    return SessionCommandDecision(
        status=SessionCommandStatus.ACCEPTED,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        current_revision=current_revision,
    )
