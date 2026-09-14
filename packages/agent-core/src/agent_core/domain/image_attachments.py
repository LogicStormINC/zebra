from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import ArtifactId, new_artifact_id

SUPPORTED_IMAGE_MEDIA_TYPES = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})


class ImageAttachmentInput(BaseModel):
    """A validated user image awaiting durable Artifact persistence."""

    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId = Field(default_factory=new_artifact_id)
    file_name: str
    media_type: str
    payload: bytes
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    source_type: Literal["user_attachment"] = "user_attachment"

    @field_validator("file_name")
    @classmethod
    def ensure_file_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("image file_name must not be blank")
        return value

    @field_validator("media_type")
    @classmethod
    def ensure_media_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ValueError("image media_type is not supported")
        return value


class ImageAttachmentContextInput(BaseModel):
    """Session-authorized image bytes recovered for one model invocation."""

    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId
    file_name: str
    media_type: str
    payload: bytes
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("file_name")
    @classmethod
    def ensure_file_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("image file_name must not be blank")
        return value

    @field_validator("media_type")
    @classmethod
    def ensure_media_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ValueError("image media_type is not supported")
        return value
