from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import ArtifactId, EventId, new_artifact_id


class TextAttachmentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId = Field(default_factory=new_artifact_id)
    file_name: str
    media_type: str
    payload: bytes
    source_type: Literal["user_attachment", "mcp_resource"] = "user_attachment"
    source_server: str | None = None
    source_id: str | None = None

    @field_validator("file_name", "media_type")
    @classmethod
    def ensure_text_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attachment fields must not be blank")
        return stripped

    @model_validator(mode="after")
    def ensure_source_is_complete(self) -> TextAttachmentInput:
        _validate_source(self.source_type, self.source_server, self.source_id)
        return self


class SessionAttachmentRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId
    message_event_id: EventId
    file_name: str
    media_type: str
    size_bytes: int = Field(ge=1)
    sha256: str
    source_type: Literal["user_attachment", "mcp_resource"] = "user_attachment"
    source_server: str | None = None
    source_id: str | None = None

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

    @model_validator(mode="after")
    def ensure_source_is_complete(self) -> SessionAttachmentRef:
        _validate_source(self.source_type, self.source_server, self.source_id)
        return self

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "attachment_id": str(self.attachment_id),
            "message_event_id": str(self.message_event_id),
            "file_name": self.file_name,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.source_type == "mcp_resource":
            result.update(
                {
                    "source_type": self.source_type,
                    "source_server": self.source_server,
                    "source_id": self.source_id,
                }
            )
        return result


class AttachmentContextInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId
    file_name: str
    media_type: str
    text: str
    source_type: Literal["user_attachment", "mcp_resource"] = "user_attachment"
    source_server: str | None = None
    source_id: str | None = None

    @field_validator("file_name", "media_type", "text")
    @classmethod
    def ensure_context_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attachment context fields must not be blank")
        return stripped

    @model_validator(mode="after")
    def ensure_source_is_complete(self) -> AttachmentContextInput:
        _validate_source(self.source_type, self.source_server, self.source_id)
        return self


def _validate_source(
    source_type: str,
    source_server: str | None,
    source_id: str | None,
) -> None:
    if source_type == "user_attachment":
        if source_server is not None or source_id is not None:
            raise ValueError("user attachments must not include MCP source fields")
        return
    if not source_server or not source_server.strip() or not source_id or not source_id.strip():
        raise ValueError("MCP resource attachments require source_server and source_id")
