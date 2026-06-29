from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from agent_core.domain.identifiers import ArtifactId, SessionId


class ArtifactPayloadStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"


class ArtifactPayloadWrite(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    kind: str
    mime_type: str
    payload: bytes
    file_name: str | None = None
    created_at: datetime

    @field_validator("kind", "mime_type")
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("artifact payload fields must not be blank")
        return stripped

    @field_validator("file_name")
    @classmethod
    def normalize_optional_file_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class StoredArtifactPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: ArtifactId
    session_id: SessionId
    kind: str
    mime_type: str
    uri: str
    sha256: str
    size_bytes: int
    created_at: datetime


class ArtifactPayloadInspection(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: ArtifactId
    status: ArtifactPayloadStatus
    payload: StoredArtifactPayload
