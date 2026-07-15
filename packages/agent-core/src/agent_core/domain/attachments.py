from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import ArtifactId, EventId, new_artifact_id


class TextAttachmentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId = Field(default_factory=new_artifact_id)
    file_name: str
    media_type: str
    payload: bytes

    @field_validator("file_name", "media_type")
    @classmethod
    def ensure_text_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attachment fields must not be blank")
        return stripped


class SessionAttachmentRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId
    message_event_id: EventId
    file_name: str
    media_type: str
    size_bytes: int = Field(ge=1)
    sha256: str

    @field_validator("file_name", "media_type")
    @classmethod
    def ensure_reference_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attachment reference fields must not be blank")
        return stripped

    @field_validator("sha256")
    @classmethod
    def ensure_sha256(cls, value: str) -> str:
        digest = value.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("attachment sha256 must be a 64-character hex digest")
        return digest

    def to_mapping(self) -> dict[str, object]:
        return {
            "attachment_id": str(self.attachment_id),
            "message_event_id": str(self.message_event_id),
            "file_name": self.file_name,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


class AttachmentContextInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId
    file_name: str
    media_type: str
    text: str

    @field_validator("file_name", "media_type", "text")
    @classmethod
    def ensure_context_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attachment context fields must not be blank")
        return stripped
