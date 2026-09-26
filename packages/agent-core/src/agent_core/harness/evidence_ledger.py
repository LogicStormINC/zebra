"""Deterministic evidence inventory derived from durable tool-result events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from agent_core.domain.events import EventType
from agent_core.domain.tools import ToolCallStatus, ToolResult
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


@dataclass(frozen=True)
class EvidenceLedger:
    successful_tool_results: int = 0
    failed_tool_results: int = 0
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return self.successful_tool_results > 0

    def cited_refs(self, answer: str) -> tuple[str, ...]:
        return tuple(ref for ref in self.evidence_refs if ref in answer)


def evidence_ledger(
    events: list[HarnessEventDraft],
    metadata: Mapping[str, object] | None = None,
) -> EvidenceLedger:
    """Collect only bounded, explicit references from successful tool results."""

    if metadata is not None and "evidence_successful_tool_results" in metadata:
        return _ledger_from_metadata(metadata)
    successful = 0
    failed = 0
    refs: set[str] = set()
    artifacts: set[str] = set()
    for event in events:
        if event.event_type is EventType.TOOL_EXECUTION_FAILED:
            failed += 1
            continue
        if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
            continue
        successful += 1
        payload = event.payload
        _collect_metadata_refs(payload.get("metadata"), refs, artifacts)
        output = payload.get("output")
        if isinstance(output, str) and output:
            try:
                parsed = json.loads(output)
            except (TypeError, ValueError):
                continue
            _collect_refs(parsed, refs, artifacts)
    return EvidenceLedger(
        successful_tool_results=successful,
        failed_tool_results=failed,
        evidence_refs=tuple(sorted(refs)),
        artifact_refs=tuple(sorted(artifacts)),
    )


def record_tool_evidence(
    metadata: Mapping[str, object],
    result: ToolResult,
) -> dict[str, object]:
    refs = set(_string_sequence(metadata.get("evidence_refs")))
    artifacts = set(_string_sequence(metadata.get("evidence_artifact_refs")))
    successful = _non_negative_int(metadata.get("evidence_successful_tool_results"))
    failed = _non_negative_int(metadata.get("evidence_failed_tool_results"))
    if result.status is ToolCallStatus.EXECUTED:
        successful += 1
        _collect_metadata_refs(result.metadata, refs, artifacts)
        if result.output:
            try:
                parsed = json.loads(result.output)
            except (TypeError, ValueError):
                parsed = None
            _collect_refs(parsed, refs, artifacts)
    else:
        failed += 1
    return {
        **metadata,
        "evidence_successful_tool_results": successful,
        "evidence_failed_tool_results": failed,
        "evidence_refs": sorted(refs)[:128],
        "evidence_artifact_refs": sorted(artifacts)[:128],
    }


def _ledger_from_metadata(metadata: Mapping[str, object]) -> EvidenceLedger:
    return EvidenceLedger(
        successful_tool_results=_non_negative_int(
            metadata.get("evidence_successful_tool_results")
        ),
        failed_tool_results=_non_negative_int(metadata.get("evidence_failed_tool_results")),
        evidence_refs=_string_sequence(metadata.get("evidence_refs")),
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


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _collect_refs(value: object, refs: set[str], artifacts: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _REFERENCE_KEYS and isinstance(item, str):
                normalized = item.strip()
                if _safe_reference(normalized):
                    refs.add(normalized)
                    if normalized.startswith("artifact://"):
                        artifacts.add(normalized)
            elif isinstance(item, Mapping | list | tuple):
                _collect_refs(item, refs, artifacts)
    elif isinstance(value, list | tuple):
        for item in value[:100]:
            _collect_refs(item, refs, artifacts)


def _collect_metadata_refs(
    value: object, refs: set[str], artifacts: set[str]
) -> None:
    _collect_refs(value, refs, artifacts)
    if not isinstance(value, Mapping):
        return
    refs.update(_string_sequence(value.get("evidence_refs")))


def _safe_reference(value: str) -> bool:
    return len(value) <= 2_048 and value.startswith(("https://", "http://", "artifact://"))


def _safe_local_reference(value: str) -> bool:
    if not value or len(value) > 2_048 or value.startswith(("/", "~")):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))
