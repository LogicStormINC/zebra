from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from agent_core.domain.identifiers import ArtifactId


class ArtifactRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: ArtifactId
    kind: str
    uri: str
    created_at: datetime

    @field_validator("kind", "uri")
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("artifact fields must not be blank")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value
