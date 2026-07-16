from __future__ import annotations

from pathlib import Path

from agent_core.domain.memories import MemoryType, MemoryVisibility

from zebra_agent_cli.memory_review_execution import (
    _queued_memory_records,
)
from zebra_agent_cli.memory_review_serialization import (
    _count_memory_types,
    _filter_preview_records,
    _projected_results,
    _serialize_records,
    _target_explanations,
    _target_reason,
    _target_scope_kind,
)


def _preview_queue_memory_review(
    *,
    database_path: Path,
    decision: str,
    memory_type: str | None,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> dict[str, object]:
    if decision not in {"confirm", "expire"}:
        error_payload: dict[str, object] = {
            "database": str(database_path),
            "status": "invalid_request",
            "reason": "decision must be either 'confirm' or 'expire'",
        }
        if expected_visibility is MemoryVisibility.REPO:
            error_payload["session_id"] = expected_scope_id
        elif expected_visibility is MemoryVisibility.USER:
            error_payload["user_id"] = expected_scope_id
        else:
            error_payload["tenant_id"] = expected_scope_id
        return error_payload
    if memory_type is not None:
        try:
            MemoryType(memory_type)
        except ValueError:
            error_payload = {
                "database": str(database_path),
                "status": "invalid_request",
                "reason": "memory_type is not supported",
            }
            if expected_visibility is MemoryVisibility.REPO:
                error_payload["session_id"] = expected_scope_id
            elif expected_visibility is MemoryVisibility.USER:
                error_payload["user_id"] = expected_scope_id
            else:
                error_payload["tenant_id"] = expected_scope_id
            return error_payload
    records = _queued_memory_records(
        database_path=database_path,
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )
    filtered_records = _filter_preview_records(records, memory_type=memory_type)
    projected_status = "confirmed" if decision == "confirm" else "expired"
    target_scope_kind = _target_scope_kind(expected_visibility)
    target_reason = _target_reason(expected_visibility)
    payload = {
        "database": str(database_path),
        "status": "ok",
        "decision": decision,
        "queue_sweep_preview": True,
        "memory_type_filter": memory_type,
        "filtered_from_queued_count": len(records),
        "queued_count": len(filtered_records),
        "target_scope_kind": target_scope_kind,
        "target_scope_id": expected_scope_id,
        "target_reason_counts": (
            {target_reason: len(filtered_records)} if filtered_records else {}
        ),
        "target_explanations": _target_explanations(
            filtered_records,
            target_scope_kind=target_scope_kind,
            target_scope_id=expected_scope_id,
            target_reason=target_reason,
        ),
        "projected_applied_count": len(filtered_records),
        "projected_memory_status": projected_status,
        "projected_by_type": _count_memory_types(filtered_records),
        "projected_results": _projected_results(
            filtered_records,
            projected_status=projected_status,
        ),
        "memory_ids": [str(record.memory_id) for record in filtered_records],
        "memories": _serialize_records(database_path=database_path, records=filtered_records),
    }
    if expected_visibility is MemoryVisibility.REPO:
        payload["session_id"] = expected_scope_id
    elif expected_visibility is MemoryVisibility.USER:
        payload["user_id"] = expected_scope_id
    else:
        payload["tenant_id"] = expected_scope_id
    return payload
