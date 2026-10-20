"""Deterministic evidence inventory derived from durable tool-result events."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from agent_core.domain.events import EventType
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.domain.web import WebTargetError, parse_web_target
from agent_core.harness.models import HarnessEventDraft

_REFERENCE_KEYS = frozenset(
    {
        "artifact_uri",
        "canonical_url",
        "original_url",
        "source_url",
        "target_url",
        "url",
        "uri",
    }
)
_MEDIA_REFERENCE_KEYS = frozenset(
    {
        "image",
        "images",
        "image_url",
        "image_urls",
        "media",
        "media_url",
        "media_urls",
        "preview_url",
        "thumbnail",
        "thumbnail_url",
        "videos",
        "video_url",
        "video_urls",
    }
)


@dataclass(frozen=True)
class EvidenceLedger:
    successful_tool_results: int = 0
    failed_tool_results: int = 0
    evidence_refs: tuple[str, ...] = ()
    media_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return self.successful_tool_results > 0

    def cited_refs(self, answer: str) -> tuple[str, ...]:
        return tuple(ref for ref in self.evidence_refs if ref in answer)


def evidence_ledger(
    events: list[HarnessEventDraft],
    metadata: Mapping[str, object] | None = None,
    *,
    answer: str = "",
) -> EvidenceLedger:
    """Collect only bounded, explicit references from successful tool results."""

    if metadata is not None and "evidence_successful_tool_results" in metadata:
        ledger = _ledger_from_metadata(metadata)
        if not answer:
            return ledger
        cited: set[str] = set()
        for event in events:
            if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
                continue
            event_refs: set[str] = set()
            _collect_metadata_refs(event.payload.get("metadata"), event_refs, set())
            cited.update(ref for ref in event_refs if ref in answer)
        # ponytail: rescue current-attempt cited refs within 128; absent receipts fail closed.
        selected = sorted(cited) + sorted(set(ledger.evidence_refs) - cited)
        return replace(ledger, evidence_refs=tuple(selected[:128]))
    successful = 0
    failed = 0
    refs: set[str] = set()
    media_refs: set[str] = set()
    artifacts: set[str] = set()
    for event in events:
        if event.event_type is EventType.TOOL_EXECUTION_FAILED:
            failed += 1
            continue
        if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
            continue
        successful += 1
        payload = event.payload
        _collect_metadata_refs(payload.get("metadata"), refs, artifacts, media_refs)
        output = payload.get("output")
        if isinstance(output, str) and output:
            try:
                parsed = json.loads(output)
            except (TypeError, ValueError):
                continue
            _collect_refs(
                parsed,
                refs,
                artifacts,
                media_refs,
                source_body_links=_verified_source_read(payload.get("metadata")),
            )
    return EvidenceLedger(
        successful_tool_results=successful,
        failed_tool_results=failed,
        evidence_refs=tuple(sorted(refs)),
        media_refs=tuple(sorted(media_refs)),
        artifact_refs=tuple(sorted(artifacts)),
    )


def record_tool_evidence(
    metadata: Mapping[str, object],
    result: ToolResult,
) -> dict[str, object]:
    refs = set(_string_sequence(metadata.get("evidence_refs")))
    sources = set(_string_sequence(metadata.get("evidence_source_refs")))
    media_refs = set(_url_sequence(metadata.get("evidence_media_refs")))
    artifacts = set(_string_sequence(metadata.get("evidence_artifact_refs")))
    successful = _non_negative_int(metadata.get("evidence_successful_tool_results"))
    failed = _non_negative_int(metadata.get("evidence_failed_tool_results"))
    if result.status is ToolCallStatus.EXECUTED:
        successful += 1
        _collect_metadata_refs(result.metadata, refs, artifacts, media_refs)
        sources.update(
            value.strip()
            for key, value in result.metadata.items()
            if key in _REFERENCE_KEYS and isinstance(value, str) and _safe_reference(value.strip())
        )
        if result.output:
            try:
                parsed = json.loads(result.output)
            except (TypeError, ValueError):
                parsed = None
            _collect_refs(
                parsed,
                refs,
                artifacts,
                media_refs,
                source_body_links=_verified_source_read(result.metadata),
            )
    else:
        failed += 1
    # ponytail: reserve actual source addresses within 128; excess discovered links are evicted.
    sources = set(sorted(sources & refs)[:128])
    selected = (sorted(sources) + sorted(refs - sources))[:128]
    return {
        **metadata,
        "evidence_source_refs": sorted(sources),
        "evidence_successful_tool_results": successful,
        "evidence_failed_tool_results": failed,
        "evidence_refs": sorted(selected),
        "evidence_media_refs": sorted(media_refs)[:128],
        "evidence_artifact_refs": sorted(artifacts)[:128],
    }


def _ledger_from_metadata(metadata: Mapping[str, object]) -> EvidenceLedger:
    return EvidenceLedger(
        successful_tool_results=_non_negative_int(metadata.get("evidence_successful_tool_results")),
        failed_tool_results=_non_negative_int(metadata.get("evidence_failed_tool_results")),
        evidence_refs=_string_sequence(metadata.get("evidence_refs")),
        media_refs=_url_sequence(metadata.get("evidence_media_refs")),
        artifact_refs=_string_sequence(metadata.get("evidence_artifact_refs")),
    )


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(
        item
        for item in value[:128]
        if isinstance(item, str) and (_safe_reference(item) or _safe_local_reference(item))
    )


def _url_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value[:128] if isinstance(item, str) and _safe_reference(item))


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _collect_refs(
    value: object,
    refs: set[str],
    artifacts: set[str],
    media_refs: set[str] | None = None,
    *,
    source_body_links: bool = False,
) -> None:
    if isinstance(value, Mapping):
        if source_body_links and media_refs is not None:
            _collect_source_body_links(value, media_refs)
        for key, item in value.items():
            if key in _MEDIA_REFERENCE_KEYS and media_refs is not None:
                _collect_media_refs(item, media_refs, artifacts)
            elif key in _REFERENCE_KEYS and isinstance(item, str):
                normalized = item.strip()
                if _safe_reference(normalized):
                    refs.add(normalized)
                    if normalized.startswith("artifact://"):
                        artifacts.add(normalized)
            elif isinstance(item, Mapping | list | tuple):
                _collect_refs(
                    item, refs, artifacts, media_refs, source_body_links=source_body_links
                )
    elif isinstance(value, list | tuple):
        for item in value[:100]:
            _collect_refs(item, refs, artifacts, media_refs, source_body_links=source_body_links)


def _verified_source_read(metadata: object) -> bool:
    if not isinstance(metadata, Mapping) or metadata.get("read_only") is not True:
        return False
    facts = metadata.get("public_facts")
    return isinstance(facts, Mapping) and facts.get("evidence_basis") == "verified_result"


def _collect_source_body_links(value: Mapping[str, object], media_refs: set[str]) -> None:
    """Observed links in a returned source body are not independently read sources."""
    source = value.get("original_url") or value.get("canonical_url")
    body = value.get("content_text")
    if not isinstance(body, str):
        return
    try:
        parse_web_target(source)
    except WebTargetError:
        return
    # ponytail: inspect at most 64 KiB/128 links per source record; larger bodies
    # need an explicit bounded source read, never an unbounded text crawl.
    for match in re.finditer(r"https://[^\s<>`\]\)\"']+", body[:65_536]):
        url = match.group().rstrip(".,;:!?，。；：！？)]}")
        if len(media_refs) >= 128:
            break
        if len(url) > 2_048:
            continue
        try:
            parse_web_target(url)
        except WebTargetError:
            continue
        media_refs.add(url)


def _collect_media_refs(value: object, media_refs: set[str], artifacts: set[str]) -> None:
    """Collect bounded media references without treating arbitrary text as evidence."""

    if isinstance(value, str):
        normalized = value.strip()
        if _safe_reference(normalized):
            media_refs.add(normalized)
            if normalized.startswith("artifact://"):
                artifacts.add(normalized)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_media_refs(item, media_refs, artifacts)
    elif isinstance(value, list | tuple):
        for item in value[:100]:
            _collect_media_refs(item, media_refs, artifacts)


def _collect_metadata_refs(
    value: object,
    refs: set[str],
    artifacts: set[str],
    media_refs: set[str] | None = None,
) -> None:
    _collect_refs(value, refs, artifacts, media_refs)
    if not isinstance(value, Mapping):
        return
    refs.update(_string_sequence(value.get("evidence_refs")))
    if media_refs is not None:
        media_refs.update(_url_sequence(value.get("evidence_media_refs")))


def _safe_reference(value: str) -> bool:
    return len(value) <= 2_048 and value.startswith(("https://", "http://", "artifact://"))


def _safe_local_reference(value: str) -> bool:
    if not value or len(value) > 2_048 or value.startswith(("/", "~")):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))
