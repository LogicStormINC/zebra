from __future__ import annotations

import unicodedata
from base64 import b64decode
from binascii import Error as Base64Error
from hashlib import sha256
from io import BytesIO

from agent_core.domain.attachments import TextAttachmentInput
from pypdf import PdfReader

MAX_ATTACHMENT_COUNT = 4
MAX_ATTACHMENT_BYTES = 65_536
MAX_ATTACHMENT_TOTAL_BYTES = 131_072
MAX_PDF_BYTES = 4_194_304
MAX_PDF_TOTAL_BYTES = 8_388_608
MAX_PDF_PAGES = 64
MAX_PDF_PAGE_CONTENT_BYTES = 8_388_608
MAX_PDF_TOTAL_CONTENT_BYTES = 16_777_216
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


def parse_attachment_inputs(value: object) -> tuple[TextAttachmentInput, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("attachments must be a list when provided")
    if len(value) > MAX_ATTACHMENT_COUNT:
        raise ValueError(f"attachments accepts at most {MAX_ATTACHMENT_COUNT} files")
    attachments: list[TextAttachmentInput] = []
    total_stored_bytes = 0
    total_pdf_bytes = 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each attachment must be an object")
        if set(item) != _FIELDS:
            raise ValueError("attachment fields must be file_name, media_type, content_base64")
        file_name = _safe_file_name(item.get("file_name"))
        media_type = _media_type(item.get("media_type"))
        max_bytes = MAX_PDF_BYTES if media_type == "application/pdf" else MAX_ATTACHMENT_BYTES
        raw_payload = _decode_payload(item.get("content_base64"), max_bytes=max_bytes)
        if media_type == "application/pdf":
            if not file_name.lower().endswith(".pdf"):
                raise ValueError("PDF attachment file_name must end with .pdf")
            total_pdf_bytes += len(raw_payload)
            if total_pdf_bytes > MAX_PDF_TOTAL_BYTES:
                raise ValueError(
                    f"PDF attachments exceed the {MAX_PDF_TOTAL_BYTES}-byte aggregate limit"
                )
            payload, page_count = _extract_pdf_text(raw_payload)
            attachment = TextAttachmentInput(
                file_name=file_name,
                media_type="text/plain",
                payload=payload,
                original_media_type=media_type,
                original_size_bytes=len(raw_payload),
                original_sha256=sha256(raw_payload).hexdigest(),
                page_count=page_count,
                extraction_status="text_extracted",
            )
        else:
            payload = _decode_text_payload(raw_payload)
            attachment = TextAttachmentInput(
                file_name=file_name,
                media_type=media_type,
                payload=payload,
            )
        total_stored_bytes += len(payload)
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
    if media_type == "application/pdf":
        return media_type
    if media_type not in SUPPORTED_TEXT_MEDIA_TYPES:
        raise ValueError("attachment media_type is not supported")
    return media_type


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


def _extract_pdf_text(payload: bytes) -> tuple[bytes, int]:
    if not payload.startswith(b"%PDF-"):
        raise ValueError("PDF attachment signature is invalid")
    try:
        reader = PdfReader(BytesIO(payload), strict=True, root_object_recovery_limit=1_000)
        if reader.is_encrypted:
            raise ValueError("encrypted PDF attachments are not supported")
        page_count = len(reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF attachment is malformed") from exc
    if page_count < 1:
        raise ValueError("PDF attachment must contain at least one page")
    if page_count > MAX_PDF_PAGES:
        raise ValueError(f"PDF attachment exceeds the {MAX_PDF_PAGES}-page limit")

    page_blocks: list[str] = []
    total_content_bytes = 0
    total_extracted_bytes = 0
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            contents = page.get_contents()
            content_bytes = len(contents.get_data()) if contents is not None else 0
        except Exception as exc:
            raise ValueError(f"PDF attachment page {page_number} content is malformed") from exc
        if content_bytes > MAX_PDF_PAGE_CONTENT_BYTES:
            raise ValueError(f"PDF attachment page {page_number} exceeds the decoded content limit")
        total_content_bytes += content_bytes
        if total_content_bytes > MAX_PDF_TOTAL_CONTENT_BYTES:
            raise ValueError("PDF attachment exceeds the decoded content aggregate limit")
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise ValueError(f"PDF attachment page {page_number} cannot be extracted") from exc
        normalized = _normalize_extracted_text(text)
        if not normalized:
            continue
        block = f"[PDF page {page_number}]\n{normalized}"
        total_extracted_bytes += len(block.encode("utf-8"))
        if total_extracted_bytes > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"PDF extracted text exceeds the {MAX_ATTACHMENT_BYTES}-byte limit")
        page_blocks.append(block)
    if not page_blocks:
        raise ValueError("PDF has no extractable text; scanned PDFs require unsupported OCR")
    return "\n\n".join(page_blocks).encode("utf-8"), page_count


def _normalize_extracted_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = normalized.replace("\x00", "")
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()
