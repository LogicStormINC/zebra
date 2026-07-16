from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element
from zipfile import BadZipFile, ZipFile, ZipInfo

from zebra_agent_api.session_document_inputs import normalize_extracted_text
from zebra_agent_api.session_ooxml_safety import (
    PACKAGE_REL_NS,
    parse_xml,
    read_xml_part,
    reject_external_relationships,
    validate_main_content_type,
    validate_package_entries,
)

MAX_XLSX_SHEETS = 32
MAX_XLSX_CELLS = 10_000
MAX_XLSX_SHARED_STRINGS = 20_000
MAX_XLSX_TEXT_BYTES = 65_536
_CONTENT_TYPES = "[Content_Types].xml"
_WORKBOOK = "xl/workbook.xml"
_WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"
_SHARED_STRINGS = "xl/sharedStrings.xml"
_MAIN_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
_SHEET_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CELL_REF = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")


def extract_xlsx_text(payload: bytes) -> tuple[bytes, int, int]:
    if not payload.startswith(b"PK\x03\x04"):
        raise ValueError("XLSX attachment ZIP signature is invalid")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            validate_package_entries(
                entries,
                label="XLSX",
                blocked_prefixes=(
                    "xl/embeddings/",
                    "xl/externalconnections/",
                    "xl/externallinks/",
                    "xl/querytables/",
                    "xl/activex/",
                    "xl/pivotcache/",
                    "xl/pivottables/",
                    "xl/vbaproject.bin",
                    "xl/connections.xml",
                ),
            )
            by_name = {entry.filename: entry for entry in entries}
            required = {_CONTENT_TYPES, _WORKBOOK, _WORKBOOK_RELS}
            if not required.issubset(by_name):
                raise ValueError("XLSX attachment is missing required package parts")
            validate_main_content_type(
                read_xml_part(archive, by_name[_CONTENT_TYPES], label="XLSX"),
                label="XLSX",
                part_name="/xl/workbook.xml",
                content_type=_MAIN_CONTENT_TYPE,
            )
            for entry in entries:
                if entry.filename.lower().endswith(".rels"):
                    reject_external_relationships(
                        read_xml_part(archive, entry, label="XLSX"), label="XLSX"
                    )
            workbook = parse_xml(
                read_xml_part(archive, by_name[_WORKBOOK], label="XLSX"),
                label="XLSX",
                part="workbook",
            )
            relationships = reject_external_relationships(
                read_xml_part(archive, by_name[_WORKBOOK_RELS], label="XLSX"), label="XLSX"
            )
            shared_strings = _shared_strings(archive, by_name)
            sheets = _sheet_parts(workbook, relationships, by_name)
            blocks, cell_count = _worksheet_blocks(archive, sheets, shared_strings)
    except ValueError:
        raise
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise ValueError("XLSX attachment is malformed") from exc
    if not blocks:
        raise ValueError("XLSX has no extractable worksheet values")
    extracted = "\n\n".join(blocks).encode("utf-8")
    if len(extracted) > MAX_XLSX_TEXT_BYTES:
        raise ValueError(f"XLSX extracted text exceeds the {MAX_XLSX_TEXT_BYTES}-byte limit")
    return extracted, len(sheets), cell_count


def _shared_strings(archive: ZipFile, by_name: dict[str, ZipInfo]) -> tuple[str, ...]:
    entry = by_name.get(_SHARED_STRINGS)
    if entry is None:
        return ()
    root = parse_xml(
        read_xml_part(archive, entry, label="XLSX"), label="XLSX", part="shared strings"
    )
    if root.tag != f"{{{_SHEET_NS}}}sst":
        raise ValueError("XLSX shared strings structure is invalid")
    values = tuple(_all_text(item) for item in root.findall(f"{{{_SHEET_NS}}}si"))
    if len(values) > MAX_XLSX_SHARED_STRINGS:
        raise ValueError("XLSX attachment exceeds the shared-string limit")
    return values


def _sheet_parts(
    workbook: Element,
    relationships: Element,
    by_name: dict[str, ZipInfo],
) -> tuple[tuple[str, ZipInfo], ...]:
    if workbook.tag != f"{{{_SHEET_NS}}}workbook":
        raise ValueError("XLSX workbook structure is invalid")
    relation_targets: dict[str, str] = {}
    for relation in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
        if relation.get("Type") != _SHEET_REL_TYPE:
            continue
        relation_id = relation.get("Id", "")
        target = relation.get("Target", "")
        if not relation_id or not target or relation_id in relation_targets:
            raise ValueError("XLSX attachment contains invalid worksheet relationships")
        relation_targets[relation_id] = target
    sheets = workbook.findall(f".//{{{_SHEET_NS}}}sheet")
    if not sheets or len(sheets) > MAX_XLSX_SHEETS:
        raise ValueError(f"XLSX attachment must contain 1 to {MAX_XLSX_SHEETS} worksheets")
    result: list[tuple[str, ZipInfo]] = []
    names: set[str] = set()
    targets: set[str] = set()
    for sheet in sheets:
        name = normalize_extracted_text(sheet.get("name", ""))
        sheet_relation_id = sheet.get(f"{{{_DOC_REL_NS}}}id")
        sheet_target = relation_targets.get(sheet_relation_id or "")
        if (
            not name
            or len(name) > 31
            or any(ord(character) < 32 or character in "[]:*?/\\" for character in name)
            or name.casefold() in names
            or not sheet_target
        ):
            raise ValueError("XLSX attachment contains invalid worksheet metadata")
        names.add(name.casefold())
        if sheet_target.startswith("/"):
            raise ValueError("XLSX attachment contains an unsafe worksheet target")
        target_path = PurePosixPath("xl", sheet_target)
        if ".." in target_path.parts:
            raise ValueError("XLSX attachment contains an unsafe worksheet target")
        normalized_target = str(target_path)
        entry = by_name.get(normalized_target)
        if (
            entry is None
            or not normalized_target.startswith("xl/worksheets/")
            or normalized_target.casefold() in targets
        ):
            raise ValueError("XLSX attachment worksheet target is invalid")
        targets.add(normalized_target.casefold())
        result.append((name, entry))
    return tuple(result)


def _worksheet_blocks(
    archive: ZipFile,
    sheets: tuple[tuple[str, ZipInfo], ...],
    shared_strings: tuple[str, ...],
) -> tuple[list[str], int]:
    blocks: list[str] = []
    total_cells = 0
    total_bytes = 0
    for sheet_name, entry in sheets:
        root = parse_xml(
            read_xml_part(archive, entry, label="XLSX"), label="XLSX", part="worksheet"
        )
        if root.tag != f"{{{_SHEET_NS}}}worksheet":
            raise ValueError("XLSX worksheet structure is invalid")
        lines: list[str] = []
        references: set[str] = set()
        for cell in root.findall(f".//{{{_SHEET_NS}}}c"):
            reference = cell.get("r", "")
            _validate_cell_reference(reference)
            if reference in references:
                raise ValueError("XLSX attachment contains duplicate cell coordinates")
            references.add(reference)
            value = _cell_value(cell, shared_strings)
            if not value:
                continue
            total_cells += 1
            if total_cells > MAX_XLSX_CELLS:
                raise ValueError(f"XLSX attachment exceeds the {MAX_XLSX_CELLS}-cell limit")
            line = f"{reference}={value}"
            total_bytes += len(line.encode("utf-8"))
            if total_bytes > MAX_XLSX_TEXT_BYTES:
                raise ValueError(
                    f"XLSX extracted text exceeds the {MAX_XLSX_TEXT_BYTES}-byte limit"
                )
            lines.append(line)
        if lines:
            blocks.append(f"[XLSX sheet: {sheet_name}]\n" + "\n".join(lines))
    return blocks, total_cells


def _cell_value(cell: Element, shared_strings: tuple[str, ...]) -> str:
    cell_type = cell.get("t", "n")
    if cell_type == "inlineStr":
        return normalize_extracted_text(_all_text(cell.find(f"{{{_SHEET_NS}}}is")))
    value_element = cell.find(f"{{{_SHEET_NS}}}v")
    raw = normalize_extracted_text(value_element.text or "") if value_element is not None else ""
    if cell_type == "s" and raw:
        try:
            index = int(raw)
            if index < 0:
                raise IndexError(index)
            return shared_strings[index]
        except (ValueError, IndexError) as exc:
            raise ValueError("XLSX attachment contains an invalid shared-string index") from exc
    if cell_type == "b":
        if raw not in {"0", "1"}:
            raise ValueError("XLSX attachment contains an invalid boolean value")
        return "FALSE" if raw == "0" else "TRUE"
    if cell_type not in {"n", "str", "e", "d", "b"}:
        raise ValueError("XLSX attachment contains an unsupported cell type")
    if cell_type == "n" and raw:
        try:
            if not Decimal(raw).is_finite():
                raise InvalidOperation
        except InvalidOperation as exc:
            raise ValueError("XLSX attachment contains an invalid numeric value") from exc
    return raw


def _validate_cell_reference(reference: str) -> None:
    matched = _CELL_REF.fullmatch(reference)
    if matched is None:
        raise ValueError("XLSX attachment contains an invalid cell coordinate")
    column, row = matched.groups()
    column_number = 0
    for character in column:
        column_number = column_number * 26 + ord(character) - 64
    if column_number > 16_384 or int(row) > 1_048_576:
        raise ValueError("XLSX attachment cell coordinate is out of range")


def _all_text(element: Element | None) -> str:
    if element is None:
        return ""
    return normalize_extracted_text(
        "".join(item.text or "" for item in element.iter(f"{{{_SHEET_NS}}}t"))
    )
