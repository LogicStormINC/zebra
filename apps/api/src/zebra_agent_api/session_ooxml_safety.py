from __future__ import annotations

import stat
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element, ParseError, fromstring
from zipfile import BadZipFile, ZipFile, ZipInfo

MAX_OOXML_ENTRIES = 256
MAX_OOXML_ENTRY_BYTES = 8_388_608
MAX_OOXML_TOTAL_EXPANDED_BYTES = 16_777_216
MAX_OOXML_COMPRESSION_RATIO = 100
CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def validate_package_entries(
    entries: list[ZipInfo],
    *,
    label: str,
    blocked_prefixes: tuple[str, ...],
    max_entries: int = MAX_OOXML_ENTRIES,
    max_entry_bytes: int = MAX_OOXML_ENTRY_BYTES,
    max_total_expanded_bytes: int = MAX_OOXML_TOTAL_EXPANDED_BYTES,
    max_compression_ratio: int = MAX_OOXML_COMPRESSION_RATIO,
    blocked_reason: str = "unsupported active or embedded content",
) -> None:
    if not entries or len(entries) > max_entries:
        raise ValueError(f"{label} attachment exceeds the {max_entries}-entry limit")
    names: set[str] = set()
    total_expanded = 0
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{label} attachment contains an unsafe package path")
        normalized_name = name.casefold()
        if normalized_name in names:
            raise ValueError(f"{label} attachment contains duplicate package parts")
        names.add(normalized_name)
        if entry.flag_bits & 0x1:
            raise ValueError(f"encrypted {label} attachments are not supported")
        mode = entry.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ValueError(f"{label} attachment contains an unsupported symbolic link")
        if entry.file_size > max_entry_bytes:
            raise ValueError(f"{label} attachment contains an oversized package part")
        total_expanded += entry.file_size
        if total_expanded > max_total_expanded_bytes:
            raise ValueError(f"{label} attachment exceeds the expanded-content limit")
        if entry.file_size and (
            entry.compress_size == 0
            or entry.file_size > entry.compress_size * max_compression_ratio
        ):
            raise ValueError(f"{label} attachment exceeds the compression-ratio limit")
        if any(normalized_name.startswith(prefix) for prefix in blocked_prefixes):
            raise ValueError(f"{label} attachment contains {blocked_reason}")


def read_xml_part(archive: ZipFile, entry: ZipInfo, *, label: str) -> bytes:
    try:
        value = archive.read(entry)
    except (BadZipFile, NotImplementedError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"{label} attachment contains an unreadable package part") from exc
    if len(value) != entry.file_size:
        raise ValueError(f"{label} attachment package metadata is inconsistent")
    if b"<!DOCTYPE" in value.upper() or b"<!ENTITY" in value.upper():
        raise ValueError(f"{label} XML declarations and entities are not supported")
    return value


def parse_xml(value: bytes, *, label: str, part: str) -> Element:
    try:
        return fromstring(value)
    except ParseError as exc:
        raise ValueError(f"{label} {part} XML is malformed") from exc


def reject_external_relationships(value: bytes, *, label: str) -> Element:
    root = parse_xml(value, label=label, part="relationships")
    if root.tag != f"{{{PACKAGE_REL_NS}}}Relationships":
        raise ValueError(f"{label} relationships structure is invalid")
    if any(
        relationship.get("TargetMode", "").strip().lower() == "external"
        for relationship in root.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    ):
        raise ValueError(f"{label} external relationships are not supported")
    return root


def validate_main_content_type(
    value: bytes,
    *,
    label: str,
    part_name: str,
    content_type: str,
) -> None:
    root = parse_xml(value, label=label, part="content types")
    if any("macroenabled" in (element.get("ContentType") or "").lower() for element in root):
        raise ValueError(f"macro-enabled {label} attachments are not supported")
    main_types = {
        element.get("ContentType")
        for element in root.findall(f"{{{CONTENT_TYPE_NS}}}Override")
        if element.get("PartName") == part_name
    }
    if main_types != {content_type}:
        raise ValueError(f"{label} attachment main content type is invalid")
