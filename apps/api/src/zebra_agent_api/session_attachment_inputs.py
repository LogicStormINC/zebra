from __future__ import annotations

from base64 import b64decode
from binascii import Error as Base64Error

from agent_core.domain.attachments import TextAttachmentInput

MAX_ATTACHMENT_COUNT = 4
MAX_ATTACHMENT_BYTES = 65_536
MAX_ATTACHMENT_TOTAL_BYTES = 131_072
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


def parse_text_attachment_inputs(value: object) -> tuple[TextAttachmentInput, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("attachments must be a list when provided")
    if len(value) > MAX_ATTACHMENT_COUNT:
        raise ValueError(f"attachments accepts at most {MAX_ATTACHMENT_COUNT} files")
    attachments: list[TextAttachmentInput] = []
    total_bytes = 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each attachment must be an object")
        if set(item) != _FIELDS:
            raise ValueError("attachment fields must be file_name, media_type, content_base64")
        file_name = _safe_file_name(item.get("file_name"))
        media_type = _media_type(item.get("media_type"))
        payload = _decode_payload(item.get("content_base64"))
        total_bytes += len(payload)
        if total_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
            raise ValueError(
                f"attachments exceed the {MAX_ATTACHMENT_TOTAL_BYTES}-byte aggregate limit"
            )
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("attachments must contain valid UTF-8 text") from exc
        if not text.strip():
            raise ValueError("attachments must not be empty or whitespace-only")
        attachments.append(
            TextAttachmentInput(
                file_name=file_name,
                media_type=media_type,
                payload=payload,
            )
        )
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
    if media_type not in SUPPORTED_TEXT_MEDIA_TYPES:
        raise ValueError("attachment media_type is not supported")
    return media_type


def _decode_payload(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("attachment content_base64 must be a non-empty string")
    if len(value) > ((MAX_ATTACHMENT_BYTES + 2) // 3) * 4:
        raise ValueError(f"attachment exceeds the {MAX_ATTACHMENT_BYTES}-byte limit")
    try:
        payload = b64decode(value, validate=True)
    except (Base64Error, ValueError) as exc:
        raise ValueError("attachment content_base64 is malformed") from exc
    if not payload:
        raise ValueError("attachments must not be empty")
    if len(payload) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"attachment exceeds the {MAX_ATTACHMENT_BYTES}-byte limit")
    return payload
