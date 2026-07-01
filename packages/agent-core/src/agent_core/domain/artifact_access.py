from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class ArtifactAccessClass(StrEnum):
    OPERATOR_SAFE = "operator_safe"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class ArtifactAccessDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    mime_type: str | None = None
    uri: str | None = None
    preview_redacted: bool = False
    preview_truncated: bool = False

    @field_validator("kind")
    @classmethod
    def ensure_kind_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("artifact access kind must not be blank")
        return stripped

    @field_validator("mime_type", "uri")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
