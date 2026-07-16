from __future__ import annotations

from pathlib import Path

from agent_core.domain.memories import MemoryVisibility

from zebra_agent_api.memory_review_execution import (
    _queued_memory_records,
)
from zebra_agent_api.memory_review_serialization import (
    _count_memory_types,
    _filter_preview_records,
    _projected_results,
    _serialize_records,
    _target_explanations,
    _target_reason,
    _target_scope_kind,
)
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_payloads import parse_queue_sweep_preview_payload


def _preview_memory_queue(
    *,
    database_path: Path,
    payload: dict[str, object],
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> ApiResponse:
    parsed = parse_queue_sweep_preview_payload(payload)
    if isinstance(parsed, ApiResponse):
        return parsed
    all_records = _queued_memory_records(
        database_path=database_path,
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )
    filtered_records = _filter_preview_records(
        all_records,
        memory_type=parsed["memory_type"],
    )
    decision = parsed["decision"]
    projected_status = "confirmed" if decision == "confirm" else "expired"
    target_scope_kind = _target_scope_kind(expected_visibility)
    target_reason = _target_reason(expected_visibility)
    body: dict[str, object] = {
        "status": "ok",
        "decision": decision,
        "queue_sweep_preview": True,
        "memory_type_filter": parsed["memory_type"],
        "filtered_from_queued_count": len(all_records),
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
        body["session_id"] = expected_scope_id
    elif expected_visibility is MemoryVisibility.USER:
        body["user_id"] = expected_scope_id
    else:
        body["tenant_id"] = expected_scope_id
    return ApiResponse(status_code=200, body=body)
