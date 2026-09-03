from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectVerification,
)
from agent_core.domain.identifiers import ArtifactId, EventId, SessionId


class ArtifactPayloadReadStatus(StrEnum):
    AVAILABLE = "payload_available"
    MISSING = "payload_missing"
    PRUNED = "payload_pruned"
    UNAVAILABLE = "payload_unavailable"


class ArtifactPayloadReadPrunedError(FileNotFoundError):
    """The payload became authoritatively pruned before its bytes were read."""


class ArtifactPayloadReadUnavailableError(RuntimeError):
    """The payload exists but is not readable in its current lifecycle state."""


class ArtifactPayloadReadInspection(BaseModel):
    """Provider-neutral payload evidence exposed to read composition only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: ArtifactId
    session_id: SessionId
    mime_type: str
    file_name: str | None = None
    size_bytes: int | None = None
    status: ArtifactPayloadReadStatus
    lifecycle_status: str
    retained_until: datetime | None = None
    pruned_at: datetime | None = None
    bound_event_id: EventId | None = None
    bound_event_sequence: int | None = None

    @field_validator("mime_type", "lifecycle_status")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("payload read fields must be non-blank and trimmed")
        return value

    @field_validator("file_name")
    @classmethod
    def normalize_file_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("retained_until", "pruned_at")
    @classmethod
    def require_timestamp(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value


class ArtifactPayloadReadPort(Protocol):
    def describe_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection | None: ...

    def inspect_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection | None: ...

    def read_payload_bytes(
        self,
        session_id: SessionId,
        uri: str,
    ) -> bytes: ...


class ArtifactPayloadObjectReadPort(Protocol):
    def verify(self, expectation: ArtifactObjectExpectation) -> ArtifactObjectVerification: ...

    def read_version_verified(
        self,
        expectation: ArtifactObjectExpectation,
        object_version: str,
    ) -> bytes: ...
