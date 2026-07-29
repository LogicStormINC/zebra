from __future__ import annotations

from base64 import b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass, field
from hashlib import sha256

from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.identifiers import ArtifactId, new_artifact_id

from zebra_agent_api.session_document_inputs import extract_docx_text, extract_pdf_text
from zebra_agent_api.session_presentation_inputs import extract_pptx_text
from zebra_agent_api.session_spreadsheet_inputs import extract_xlsx_text

MAX_ATTACHMENT_COUNT = 4
MAX_ATTACHMENT_BYTES = 65_536
MAX_ATTACHMENT_TOTAL_BYTES = 131_072
MAX_PDF_BYTES = 4_194_304
MAX_DOCX_BYTES = 4_194_304
MAX_XLSX_BYTES = 4_194_304
MAX_PPTX_BYTES = 4_194_304
MAX_DOCUMENT_TOTAL_BYTES = 8_388_608
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_FILE_NAME_LENGTH = 255
SUPPORTED_TEXT_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/yaml",
        "text/css",
        "text/csv",
        "text/html",
        "text/javascript",
        "text/markdown",
        "text/plain",
        "text/yaml",
    }
)
_FIELDS = frozenset({"file_name", "media_type", "content_base64"})
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png"})
_IMAGE_EXTENSIONS = {
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
}


@dataclass(frozen=True)
class ImageAttachmentInput:
    file_name: str
    media_type: str
    payload: bytes
    attachment_id: ArtifactId = field(default_factory=new_artifact_id)


# Compatibility aliases retained for callers and focused limit tests.
_extract_pdf_text = extract_pdf_text
_extract_docx_text = extract_docx_text
_extract_xlsx_text = extract_xlsx_text
_extract_pptx_text = extract_pptx_text


def parse_attachment_inputs(
    value: object,
) -> tuple[TextAttachmentInput | ImageAttachmentInput, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("attachments must be a list when provided")
    if len(value) > MAX_ATTACHMENT_COUNT:
        raise ValueError(f"attachments accepts at most {MAX_ATTACHMENT_COUNT} files")
    attachments: list[TextAttachmentInput | ImageAttachmentInput] = []
    total_stored_bytes = 0
    total_document_bytes = 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each attachment must be an object")
        if set(item) != _FIELDS:
            raise ValueError("attachment fields must be file_name, media_type, content_base64")
        file_name = _safe_file_name(item.get("file_name"))
        media_type = _media_type(item.get("media_type"))
        max_bytes = (
            MAX_IMAGE_BYTES
            if media_type in IMAGE_MEDIA_TYPES
            else MAX_PDF_BYTES
            if media_type == "application/pdf"
            else MAX_DOCX_BYTES
            if media_type == DOCX_MEDIA_TYPE
            else MAX_XLSX_BYTES
            if media_type == XLSX_MEDIA_TYPE
            else MAX_PPTX_BYTES
            if media_type == PPTX_MEDIA_TYPE
            else MAX_ATTACHMENT_BYTES
        )
        raw_payload = _decode_payload(item.get("content_base64"), max_bytes=max_bytes)
        attachment: TextAttachmentInput | ImageAttachmentInput
        if media_type in IMAGE_MEDIA_TYPES:
            if not any(
                file_name.lower().endswith(suffix) for suffix in _IMAGE_EXTENSIONS[media_type]
            ):
                raise ValueError(f"{media_type} attachment file_name has an inconsistent extension")
            _validate_image_magic(media_type, raw_payload)
            attachment = ImageAttachmentInput(
                file_name=file_name,
                media_type=media_type,
                payload=raw_payload,
            )
        elif media_type in {
            "application/pdf",
            DOCX_MEDIA_TYPE,
            XLSX_MEDIA_TYPE,
            PPTX_MEDIA_TYPE,
        }:
            expected_extension = {
                "application/pdf": ".pdf",
                DOCX_MEDIA_TYPE: ".docx",
                XLSX_MEDIA_TYPE: ".xlsx",
                PPTX_MEDIA_TYPE: ".pptx",
            }[media_type]
            label = expected_extension[1:].upper()
            if not file_name.lower().endswith(expected_extension):
                raise ValueError(f"{label} attachment file_name must end with {expected_extension}")
            total_document_bytes += len(raw_payload)
            if total_document_bytes > MAX_DOCUMENT_TOTAL_BYTES:
                raise ValueError(
                    "document attachments exceed the "
                    f"{MAX_DOCUMENT_TOTAL_BYTES}-byte aggregate limit"
                )
            unit_count: int | None = None
            sheet_count: int | None = None
            cell_count: int | None = None
            slide_count: int | None = None
            if media_type == XLSX_MEDIA_TYPE:
                payload, sheet_count, cell_count = _extract_xlsx_text(raw_payload)
            elif media_type == PPTX_MEDIA_TYPE:
                payload, slide_count = _extract_pptx_text(raw_payload)
            else:
                payload, unit_count = (
                    _extract_pdf_text(raw_payload)
                    if media_type == "application/pdf"
                    else _extract_docx_text(raw_payload)
                )
            attachment = TextAttachmentInput(
                file_name=file_name,
                media_type="text/plain",
                payload=payload,
                original_media_type=media_type,
                original_size_bytes=len(raw_payload),
                original_sha256=sha256(raw_payload).hexdigest(),
                page_count=unit_count if media_type == "application/pdf" else None,
                paragraph_count=unit_count if media_type == DOCX_MEDIA_TYPE else None,
                worksheet_count=sheet_count,
                cell_count=cell_count,
                slide_count=slide_count,
                extraction_status="text_extracted",
            )
        else:
            payload = _decode_text_payload(raw_payload)
            attachment = TextAttachmentInput(
                file_name=file_name,
                media_type=media_type,
                payload=payload,
            )
        if isinstance(attachment, TextAttachmentInput):
            total_stored_bytes += len(attachment.payload)
            if total_stored_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
                raise ValueError(
                    f"attachments exceed the {MAX_ATTACHMENT_TOTAL_BYTES}-byte aggregate limit"
                )
        attachments.append(attachment)
    return tuple(attachments)


def _safe_file_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("attachment file_name must be a non-blank string")
    name = value.strip()
    if len(name) > MAX_FILE_NAME_LENGTH:
        raise ValueError(f"attachment file_name exceeds {MAX_FILE_NAME_LENGTH} characters")
    if (
        name in {".", ".."}
        or any(character in name for character in ("/", "\\"))
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        raise ValueError("attachment file_name must be a safe basename")
    return name


def _media_type(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("attachment media_type must be a string")
    media_type = value.strip().lower()
    if media_type in IMAGE_MEDIA_TYPES:
        return media_type
    if media_type == "application/pdf":
        return media_type
    if media_type == DOCX_MEDIA_TYPE:
        return media_type
    if media_type == XLSX_MEDIA_TYPE:
        return media_type
    if media_type == PPTX_MEDIA_TYPE:
        return media_type
    if media_type not in SUPPORTED_TEXT_MEDIA_TYPES:
        raise ValueError("attachment media_type is not supported")
    return media_type


def _validate_image_magic(media_type: str, payload: bytes) -> None:
    valid = (
        payload.startswith(b"\xff\xd8\xff")
        if media_type == "image/jpeg"
        else payload.startswith(b"\x89PNG\r\n\x1a\n")
    )
    if not valid:
        raise ValueError(f"{media_type} attachment magic bytes are invalid")


def _decode_payload(value: object, *, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("attachment content_base64 must be a non-empty string")
    if len(value) > ((max_bytes + 2) // 3) * 4:
        raise ValueError(f"attachment exceeds the {max_bytes}-byte limit")
    try:
        payload = b64decode(value, validate=True)
    except (Base64Error, ValueError) as exc:
        raise ValueError("attachment content_base64 is malformed") from exc
    if not payload:
        raise ValueError("attachments must not be empty")
    if len(payload) > max_bytes:
        raise ValueError(f"attachment exceeds the {max_bytes}-byte limit")
    return payload


def _decode_text_payload(payload: bytes) -> bytes:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("attachments must contain valid UTF-8 text") from exc
    if not text.strip():
        raise ValueError("attachments must not be empty or whitespace-only")
    return payload
