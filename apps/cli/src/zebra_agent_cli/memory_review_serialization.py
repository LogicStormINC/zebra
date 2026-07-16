from __future__ import annotations

from pathlib import Path

from agent_core.application import serialize_scoped_memory_inventory
from agent_core.domain.memories import MemoryRecord, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore


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


def _not_found_payload(
    *,
    database_path: Path,
    memory_id: str,
    visibility: MemoryVisibility,
    scope_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "memory_id": memory_id,
        "database": str(database_path),
        "status": "not_found",
    }
    if visibility is MemoryVisibility.REPO:
        payload["session_id"] = scope_id
    elif visibility is MemoryVisibility.USER:
        payload["user_id"] = scope_id
    else:
        payload["tenant_id"] = scope_id
    return payload


def _bulk_outcome_payload(
    *,
    memory_id: str,
    outcome: str,
    status: str,
    reason: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "memory_id": memory_id,
        "outcome": outcome,
        "status": status,
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


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
