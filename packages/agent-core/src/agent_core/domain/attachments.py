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
    source_type: Literal["user_attachment", "mcp_resource", "mcp_prompt"] = "user_attachment"
    source_server: str | None = None
    source_id: str | None = None
    source_argument_names: tuple[str, ...] = ()
    original_media_type: str | None = None
    original_size_bytes: int | None = Field(default=None, ge=1)
    original_sha256: str | None = None
    page_count: int | None = Field(default=None, ge=1)
    extraction_status: Literal["text_extracted"] | None = None

    @field_validator("file_name", "media_type")
    @classmethod
    def ensure_text_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attachment fields must not be blank")
        return stripped

    @field_validator("original_sha256")
    @classmethod
    def ensure_original_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_sha256(value, field_name="original attachment sha256")

    @model_validator(mode="after")
    def ensure_source_is_complete(self) -> TextAttachmentInput:
        _validate_source(
            self.source_type,
            self.source_server,
            self.source_id,
            self.source_argument_names,
        )
        _validate_document_provenance(
            self.source_type,
            self.original_media_type,
            self.original_size_bytes,
            self.original_sha256,
            self.page_count,
            self.extraction_status,
        )
        return self


class SessionAttachmentRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId
    message_event_id: EventId
    file_name: str
    media_type: str
    size_bytes: int = Field(ge=1)
    sha256: str
    source_type: Literal["user_attachment", "mcp_resource", "mcp_prompt"] = "user_attachment"
    source_server: str | None = None
    source_id: str | None = None
    source_argument_names: tuple[str, ...] = ()
    original_media_type: str | None = None
    original_size_bytes: int | None = Field(default=None, ge=1)
    original_sha256: str | None = None
    page_count: int | None = Field(default=None, ge=1)
    extraction_status: Literal["text_extracted"] | None = None

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
        return _normalized_sha256(value, field_name="attachment sha256")

    @field_validator("original_sha256")
    @classmethod
    def ensure_original_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_sha256(value, field_name="original attachment sha256")

    @model_validator(mode="after")
    def ensure_source_is_complete(self) -> SessionAttachmentRef:
        _validate_source(
            self.source_type,
            self.source_server,
            self.source_id,
            self.source_argument_names,
        )
        _validate_document_provenance(
            self.source_type,
            self.original_media_type,
            self.original_size_bytes,
            self.original_sha256,
            self.page_count,
            self.extraction_status,
        )
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
        if self.source_type in {"mcp_resource", "mcp_prompt"}:
            result.update(
                {
                    "source_type": self.source_type,
                    "source_server": self.source_server,
                    "source_id": self.source_id,
                }
            )
        if self.source_type == "mcp_prompt":
            result["source_argument_names"] = list(self.source_argument_names)
        if self.original_media_type is not None:
            result.update(
                {
                    "original_media_type": self.original_media_type,
                    "original_size_bytes": self.original_size_bytes,
                    "original_sha256": self.original_sha256,
                    "page_count": self.page_count,
                    "extraction_status": self.extraction_status,
                }
            )
        return result


class AttachmentContextInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: ArtifactId
    file_name: str
    media_type: str
    text: str
    source_type: Literal["user_attachment", "mcp_resource", "mcp_prompt"] = "user_attachment"
    source_server: str | None = None
    source_id: str | None = None
    source_argument_names: tuple[str, ...] = ()
    original_media_type: str | None = None
    original_size_bytes: int | None = Field(default=None, ge=1)
    original_sha256: str | None = None
    page_count: int | None = Field(default=None, ge=1)
    extraction_status: Literal["text_extracted"] | None = None

    @field_validator("file_name", "media_type", "text")
    @classmethod
    def ensure_context_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attachment context fields must not be blank")
        return stripped

    @field_validator("original_sha256")
    @classmethod
    def ensure_original_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_sha256(value, field_name="original attachment sha256")

    @model_validator(mode="after")
    def ensure_source_is_complete(self) -> AttachmentContextInput:
        _validate_source(
            self.source_type,
            self.source_server,
            self.source_id,
            self.source_argument_names,
        )
        _validate_document_provenance(
            self.source_type,
            self.original_media_type,
            self.original_size_bytes,
            self.original_sha256,
            self.page_count,
            self.extraction_status,
        )
        return self


def _validate_source(
    source_type: str,
    source_server: str | None,
    source_id: str | None,
    source_argument_names: tuple[str, ...],
) -> None:
    if source_type == "user_attachment":
        if source_server is not None or source_id is not None or source_argument_names:
            raise ValueError("user attachments must not include MCP source fields")
        return
    if not source_server or not source_server.strip() or not source_id or not source_id.strip():
        raise ValueError("MCP attachments require source_server and source_id")
    if source_type == "mcp_resource" and source_argument_names:
        raise ValueError("MCP resource attachments must not include argument names")
    if source_type == "mcp_prompt":
        normalized = tuple(name.strip() for name in source_argument_names)
        if normalized != source_argument_names or any(not name for name in normalized):
            raise ValueError("MCP prompt argument names must be non-blank and normalized")
        if len(set(normalized)) != len(normalized) or tuple(sorted(normalized)) != normalized:
            raise ValueError("MCP prompt argument names must be unique and sorted")


def _validate_document_provenance(
    source_type: str,
    original_media_type: str | None,
    original_size_bytes: int | None,
    original_sha256: str | None,
    page_count: int | None,
    extraction_status: str | None,
) -> None:
    fields = (
        original_media_type,
        original_size_bytes,
        original_sha256,
        page_count,
        extraction_status,
    )
    if not any(value is not None for value in fields):
        return
    if source_type != "user_attachment":
        raise ValueError("only user attachments may include document provenance")
    if any(value is None for value in fields):
        raise ValueError("document provenance must be complete")
    if original_media_type != "application/pdf":
        raise ValueError("document provenance media type must be application/pdf")
    if extraction_status != "text_extracted":
        raise ValueError("document extraction status is not supported")


def _normalized_sha256(value: str, *, field_name: str) -> str:
    digest = value.strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be a 64-character hex digest")
    return digest
