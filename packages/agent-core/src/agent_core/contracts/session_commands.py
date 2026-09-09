from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.contracts.turn_events import validate_turn_identity
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
    expected_revision: int = Field(ge=0, strict=True)
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
            if worker_id is not None and (not isinstance(worker_id, str) or not worker_id.strip()):
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

    def event_payload(
        self,
        *,
        extension_snapshot_digest: str | None = None,
        extension_turn_id: str | None = None,
    ) -> dict[str, object]:
        return SessionCommandAcceptedPayload(
            command_id=str(self.command_id),
            session_id=str(self.session_id),
            kind=self.kind,
            expected_revision=self.expected_revision,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            fingerprint=self.fingerprint,
            extension_snapshot_digest=extension_snapshot_digest,
            extension_turn_id=extension_turn_id,
        ).model_dump(mode="json", exclude_none=True)


class SessionCommandAcceptedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    session_id: str
    kind: SessionCommandKind
    expected_revision: int = Field(ge=0, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
    payload: dict[str, object]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    extension_snapshot_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    extension_turn_id: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def require_complete_extension_binding(self) -> SessionCommandAcceptedPayload:
        values = (self.extension_snapshot_digest, self.extension_turn_id)
        if (values[0] is None) != (values[1] is None):
            raise ValueError("extension snapshot binding must be complete")
        return self

    @field_validator("command_id", "session_id")
    @classmethod
    def validate_uuid_text(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise ValueError("command identity must be a UUID") from exc

    @field_validator("extension_turn_id")
    @classmethod
    def validate_extension_turn_identity(cls, value: str | None) -> str | None:
        return None if value is None else validate_turn_identity(value)


def validate_accepted_session_command(
    payload: dict[str, object],
    *,
    session_id: SessionId,
    idempotency_key: str | None,
) -> SessionCommandAcceptedPayload:
    """Prove an accepted event still represents its original command intent."""

    accepted = SessionCommandAcceptedPayload.model_validate(payload)
    command = SessionCommand(
        command_id=UUID(accepted.command_id),
        session_id=SessionId(UUID(accepted.session_id)),
        kind=accepted.kind,
        expected_revision=accepted.expected_revision,
        idempotency_key=accepted.idempotency_key,
        payload=accepted.payload,
    )
    if (
        accepted.session_id != str(session_id)
        or accepted.idempotency_key != idempotency_key
        or accepted.fingerprint != command.fingerprint
    ):
        raise ValueError("accepted command integrity check failed")
    return accepted


def is_command_message_materialization(
    *,
    causation_id: UUID | None,
    idempotency_key: str | None,
    accepted_event_id: UUID,
    accepted_idempotency_key: str,
) -> bool:
    """Match only the canonical Rabbit association or strict legacy form."""

    return (
        causation_id == accepted_event_id
        and idempotency_key == f"command-input:{accepted_event_id}"
    ) or (
        causation_id is None
        and idempotency_key == f"{accepted_idempotency_key}:message"
    )


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
