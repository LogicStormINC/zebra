from __future__ import annotations

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

MAX_PPTX_SLIDES = 64
MAX_PPTX_TEXT_BYTES = 65_536
_CONTENT_TYPES = "[Content_Types].xml"
_PRESENTATION = "ppt/presentation.xml"
_PRESENTATION_RELS = "ppt/_rels/presentation.xml.rels"
_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)
_SLIDE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
)
_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def extract_pptx_text(payload: bytes) -> tuple[bytes, int]:
    if not payload.startswith(b"PK\x03\x04"):
        raise ValueError("PPTX attachment ZIP signature is invalid")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            validate_package_entries(
                entries,
                label="PPTX",
                blocked_prefixes=(
                    "ppt/embeddings/",
                    "ppt/activex/",
                    "ppt/ctrlprops/",
                    "ppt/externallinks/",
                    "ppt/vbaproject.bin",
                ),
            )
            by_name = {entry.filename: entry for entry in entries}
            required = {_CONTENT_TYPES, _PRESENTATION, _PRESENTATION_RELS}
            if not required.issubset(by_name):
                raise ValueError("PPTX attachment is missing required package parts")
            validate_main_content_type(
                read_xml_part(archive, by_name[_CONTENT_TYPES], label="PPTX"),
                label="PPTX",
                part_name="/ppt/presentation.xml",
                content_type=_MAIN_CONTENT_TYPE,
            )
            for entry in entries:
                if entry.filename.lower().endswith(".rels"):
                    reject_external_relationships(
                        read_xml_part(archive, entry, label="PPTX"), label="PPTX"
                    )
            presentation = parse_xml(
                read_xml_part(archive, by_name[_PRESENTATION], label="PPTX"),
                label="PPTX",
                part="presentation",
            )
            relationships = reject_external_relationships(
                read_xml_part(archive, by_name[_PRESENTATION_RELS], label="PPTX"),
                label="PPTX",
            )
            slides = _slide_parts(presentation, relationships, by_name)
            blocks = _slide_blocks(archive, slides)
    except ValueError:
        raise
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise ValueError("PPTX attachment is malformed") from exc
    if not blocks:
        raise ValueError("PPTX has no extractable visible slide text")
    extracted = "\n\n".join(blocks).encode("utf-8")
    if len(extracted) > MAX_PPTX_TEXT_BYTES:
        raise ValueError(f"PPTX extracted text exceeds the {MAX_PPTX_TEXT_BYTES}-byte limit")
    return extracted, len(slides)


def _slide_parts(
    presentation: Element,
    relationships: Element,
    by_name: dict[str, ZipInfo],
) -> tuple[ZipInfo, ...]:
    if presentation.tag != f"{{{_PRESENTATION_NS}}}presentation":
        raise ValueError("PPTX presentation structure is invalid")
    relation_targets: dict[str, str] = {}
    for relation in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
        if relation.get("Type") != _SLIDE_REL_TYPE:
            continue
        relation_id = relation.get("Id", "")
        target = relation.get("Target", "")
        if not relation_id or not target or relation_id in relation_targets:
            raise ValueError("PPTX attachment contains invalid slide relationships")
        relation_targets[relation_id] = target
    slide_ids = presentation.findall(
        f"./{{{_PRESENTATION_NS}}}sldIdLst/{{{_PRESENTATION_NS}}}sldId"
    )
    if not slide_ids or len(slide_ids) > MAX_PPTX_SLIDES:
        raise ValueError(f"PPTX attachment must contain 1 to {MAX_PPTX_SLIDES} slides")
    result: list[ZipInfo] = []
    targets: set[str] = set()
    for slide_id in slide_ids:
        slide_target = relation_targets.get(slide_id.get(f"{{{_DOC_REL_NS}}}id", ""))
        if not slide_target or slide_target.startswith("/"):
            raise ValueError("PPTX attachment contains an unsafe slide target")
        target_path = PurePosixPath("ppt", slide_target)
        if ".." in target_path.parts:
            raise ValueError("PPTX attachment contains an unsafe slide target")
        normalized_target = str(target_path)
        entry = by_name.get(normalized_target)
        if (
            entry is None
            or not normalized_target.startswith("ppt/slides/")
            or normalized_target.casefold() in targets
        ):
            raise ValueError("PPTX attachment contains invalid slide metadata")
        targets.add(normalized_target.casefold())
        result.append(entry)
    return tuple(result)


def _slide_blocks(archive: ZipFile, slides: tuple[ZipInfo, ...]) -> tuple[str, ...]:
    blocks: list[str] = []
    for index, entry in enumerate(slides, start=1):
        root = parse_xml(
            read_xml_part(archive, entry, label="PPTX"),
            label="PPTX",
            part=f"slide {index}",
        )
        if root.tag != f"{{{_PRESENTATION_NS}}}sld":
            raise ValueError("PPTX slide structure is invalid")
        paragraphs = []
        for paragraph in root.iter(f"{{{_DRAWING_NS}}}p"):
            text = normalize_extracted_text(
                "".join(node.text or "" for node in paragraph.iter(f"{{{_DRAWING_NS}}}t"))
            )
            if text:
                paragraphs.append(text)
        if paragraphs:
            blocks.append(f"[PPTX slide: {index}]\n" + "\n".join(paragraphs))
    return tuple(blocks)
