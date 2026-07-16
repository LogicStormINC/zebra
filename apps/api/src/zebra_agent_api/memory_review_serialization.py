from __future__ import annotations

from pathlib import Path

from agent_core.application import MemoryReviewResult, serialize_scoped_memory_inventory
from agent_core.domain.memories import MemoryRecord, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore

from zebra_agent_api.responses import ApiResponse


def _serialize_records(
    *,
    database_path: Path,
    records: list[MemoryRecord],
) -> list[dict[str, object]]:
    return serialize_scoped_memory_inventory(
        records,
        SQLiteEventStore(database_path).list_for_session,
    )


def _count_memory_types(records: list[MemoryRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        memory_type = record.memory_type.value
        counts[memory_type] = counts.get(memory_type, 0) + 1
    return counts


def _filter_preview_records(
    records: list[MemoryRecord],
    *,
    memory_type: str | None,
) -> list[MemoryRecord]:
    if memory_type is None:
        return records
    normalized_type = MemoryType(memory_type)
    return [record for record in records if record.memory_type is normalized_type]


def _projected_results(
    records: list[MemoryRecord],
    *,
    projected_status: str,
) -> list[dict[str, object]]:
    return [
        {
            "memory_id": str(record.memory_id),
            "memory_type": record.memory_type.value,
            "current_status": record.status.value,
            "projected_status": projected_status,
        }
        for record in records
    ]


def _target_explanations(
    records: list[MemoryRecord],
    *,
    target_scope_kind: str,
    target_scope_id: str,
    target_reason: str,
) -> list[dict[str, object]]:
    return [
        {
            "memory_id": str(record.memory_id),
            "memory_type": record.memory_type.value,
            "current_status": record.status.value,
            "target_scope_kind": target_scope_kind,
            "target_scope_id": target_scope_id,
            "target_reason": target_reason,
        }
        for record in records
    ]


def _target_scope_kind(visibility: MemoryVisibility) -> str:
    if visibility is MemoryVisibility.REPO:
        return "session"
    if visibility is MemoryVisibility.USER:
        return "user"
    return "tenant"


def _target_reason(visibility: MemoryVisibility) -> str:
    if visibility is MemoryVisibility.REPO:
        return "repo_candidate_for_session"
    if visibility is MemoryVisibility.USER:
        return "user_candidate_for_user"
    return "tenant_candidate_for_tenant"


def _review_response_body(
    *,
    session_id: str,
    memory_id: str,
    decision: str,
    result: MemoryReviewResult,
    session_status: str,
    visibility: MemoryVisibility,
    scope_id: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "session_id": session_id,
        "memory_id": memory_id,
        "decision": decision,
        "event_type": result.event.event_type.value,
        "sequence": result.event.sequence,
        "status": session_status,
        "memory_status": result.record.status.value,
        "superseded_memory_ids": [
            str(superseded.memory_id) for superseded in result.superseded_records
        ],
        "duplicate_of_memory_id": (
            None if result.duplicate_of is None else str(result.duplicate_of.memory_id)
        ),
    }
    if visibility is MemoryVisibility.USER:
        body["user_id"] = scope_id
    elif visibility is MemoryVisibility.TENANT:
        body["tenant_id"] = scope_id
    return body


def _bulk_outcome(
    *,
    memory_id: str,
    outcome: str,
    status: str,
    reason: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "memory_id": memory_id,
        "outcome": outcome,
        "status": status,
    }
    if reason is not None:
        body["reason"] = reason
    return body


def _not_found_response(
    *,
    memory_id: str,
    visibility: MemoryVisibility,
    scope_id: str,
) -> ApiResponse:
    body: dict[str, object] = {
        "memory_id": memory_id,
        "status": "not_found",
    }
    if visibility is MemoryVisibility.REPO:
        body["session_id"] = scope_id
    elif visibility is MemoryVisibility.USER:
        body["user_id"] = scope_id
    else:
        body["tenant_id"] = scope_id
    return ApiResponse(status_code=404, body=body)


def _scope_matches(
    record: MemoryRecord,
    visibility: MemoryVisibility,
    scope_id: str,
) -> bool:
    if record.visibility is not visibility:
        return False
    if visibility is MemoryVisibility.REPO:
        return record.source_session_id is not None and str(record.source_session_id) == scope_id
    if visibility is MemoryVisibility.USER:
        return record.user_id == scope_id
    return record.tenant_id == scope_id
