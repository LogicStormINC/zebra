from __future__ import annotations

import stat
import unicodedata
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element, ParseError, fromstring
from zipfile import BadZipFile, ZipFile, ZipInfo

from pypdf import PdfReader

MAX_EXTRACTED_TEXT_BYTES = 65_536
MAX_PDF_PAGES = 64
MAX_PDF_PAGE_CONTENT_BYTES = 8_388_608
MAX_PDF_TOTAL_CONTENT_BYTES = 16_777_216
MAX_DOCX_ENTRIES = 256
MAX_DOCX_ENTRY_BYTES = 8_388_608
MAX_DOCX_TOTAL_EXPANDED_BYTES = 16_777_216
MAX_DOCX_COMPRESSION_RATIO = 100

_CONTENT_TYPES = "[Content_Types].xml"
_DOCUMENT_XML = "word/document.xml"
_DOCX_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def extract_pdf_text(payload: bytes) -> tuple[bytes, int]:
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
        normalized = normalize_extracted_text(text)
        if not normalized:
            continue
        block = f"[PDF page {page_number}]\n{normalized}"
        total_extracted_bytes += len(block.encode("utf-8"))
        if total_extracted_bytes > MAX_EXTRACTED_TEXT_BYTES:
            raise ValueError(
                f"PDF extracted text exceeds the {MAX_EXTRACTED_TEXT_BYTES}-byte limit"
            )
        page_blocks.append(block)
    if not page_blocks:
        raise ValueError("PDF has no extractable text; scanned PDFs require unsupported OCR")
    return "\n\n".join(page_blocks).encode("utf-8"), page_count


def extract_docx_text(payload: bytes) -> tuple[bytes, int]:
    if not payload.startswith(b"PK\x03\x04"):
        raise ValueError("DOCX attachment ZIP signature is invalid")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            _validate_docx_entries(entries)
            by_name = {entry.filename: entry for entry in entries}
            if _CONTENT_TYPES not in by_name or _DOCUMENT_XML not in by_name:
                raise ValueError("DOCX attachment is missing required package parts")
            content_types = _read_xml_part(archive, by_name[_CONTENT_TYPES])
            _validate_content_types(content_types)
            for entry in entries:
                if entry.filename.lower().endswith(".rels"):
                    _validate_relationships(_read_xml_part(archive, entry))
            document = _read_xml_part(archive, by_name[_DOCUMENT_XML])
    except ValueError:
        raise
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise ValueError("DOCX attachment is malformed") from exc

    root = _parse_xml(document, label="main document")
    if root.tag != f"{{{_WORD_NS}}}document" or root.find(f"{{{_WORD_NS}}}body") is None:
        raise ValueError("DOCX main document structure is invalid")
    if root.find(f".//{{{_WORD_NS}}}altChunk") is not None:
        raise ValueError("DOCX altChunk content is not supported")
    blocks = [_paragraph_text(paragraph) for paragraph in root.iter(f"{{{_WORD_NS}}}p")]
    blocks = [block for block in blocks if block]
    if not blocks:
        raise ValueError("DOCX has no extractable body or table text")
    extracted = normalize_extracted_text("\n\n".join(blocks)).encode("utf-8")
    if len(extracted) > MAX_EXTRACTED_TEXT_BYTES:
        raise ValueError(
            f"DOCX extracted text exceeds the {MAX_EXTRACTED_TEXT_BYTES}-byte limit"
        )
    return extracted, len(blocks)


def _validate_docx_entries(entries: list[ZipInfo]) -> None:
    if not entries or len(entries) > MAX_DOCX_ENTRIES:
        raise ValueError(f"DOCX attachment exceeds the {MAX_DOCX_ENTRIES}-entry limit")
    names: set[str] = set()
    total_expanded = 0
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
            raise ValueError("DOCX attachment contains an unsafe package path")
        normalized_name = name.casefold()
        if normalized_name in names:
            raise ValueError("DOCX attachment contains duplicate package parts")
        names.add(normalized_name)
        if entry.flag_bits & 0x1:
            raise ValueError("encrypted DOCX attachments are not supported")
        mode = entry.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ValueError("DOCX attachment contains an unsupported symbolic link")
        if entry.file_size > MAX_DOCX_ENTRY_BYTES:
            raise ValueError("DOCX attachment contains an oversized package part")
        total_expanded += entry.file_size
        if total_expanded > MAX_DOCX_TOTAL_EXPANDED_BYTES:
            raise ValueError("DOCX attachment exceeds the expanded-content limit")
        if entry.file_size and (
            entry.compress_size == 0
            or entry.file_size > entry.compress_size * MAX_DOCX_COMPRESSION_RATIO
        ):
            raise ValueError("DOCX attachment exceeds the compression-ratio limit")
        lowered = name.lower()
        if lowered.endswith("vbaproject.bin") or lowered.startswith("word/embeddings/"):
            raise ValueError("DOCX macros and embedded objects are not supported")


def _read_xml_part(archive: ZipFile, entry: ZipInfo) -> bytes:
    try:
        value = archive.read(entry)
    except (BadZipFile, NotImplementedError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError("DOCX attachment contains an unreadable package part") from exc
    if len(value) != entry.file_size:
        raise ValueError("DOCX attachment package metadata is inconsistent")
    if b"<!DOCTYPE" in value.upper() or b"<!ENTITY" in value.upper():
        raise ValueError("DOCX XML declarations and entities are not supported")
    return value


def _validate_content_types(value: bytes) -> None:
    root = _parse_xml(value, label="content types")
    if any("macroenabled" in (element.get("ContentType") or "").lower() for element in root):
        raise ValueError("macro-enabled DOCX attachments are not supported")
    main_types = {
        element.get("ContentType")
        for element in root.findall(f"{{{_CONTENT_TYPE_NS}}}Override")
        if element.get("PartName") == "/word/document.xml"
    }
    if main_types != {_DOCX_MAIN_CONTENT_TYPE}:
        raise ValueError("DOCX attachment main document content type is invalid")


def _validate_relationships(value: bytes) -> None:
    root = _parse_xml(value, label="relationships")
    if root.tag != f"{{{_PACKAGE_REL_NS}}}Relationships":
        raise ValueError("DOCX relationships structure is invalid")
    if any(
        relationship.get("TargetMode", "").strip().lower() == "external"
        for relationship in root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    ):
        raise ValueError("DOCX external relationships are not supported")


def _parse_xml(value: bytes, *, label: str) -> Element:
    try:
        return fromstring(value)
    except ParseError as exc:
        raise ValueError(f"DOCX {label} XML is malformed") from exc


def _paragraph_text(paragraph: Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == f"{{{_WORD_NS}}}t":
            parts.append(element.text or "")
        elif element.tag == f"{{{_WORD_NS}}}tab":
            parts.append("\t")
        elif element.tag in {f"{{{_WORD_NS}}}br", f"{{{_WORD_NS}}}cr"}:
            parts.append("\n")
    return normalize_extracted_text("".join(parts))


def normalize_extracted_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = normalized.replace("\x00", "")
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()
