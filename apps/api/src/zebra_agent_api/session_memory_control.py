from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.application import (
    MemoryReviewAction,
    MemoryReviewCommand,
    MemoryReviewService,
    memory_review_scope_query,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_payloads import parse_approval_decision_payload


def review_session_memory(
    *,
    database_path: Path,
    session_id: str,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
) -> ApiResponse:
    parsed = parse_approval_decision_payload(
        payload,
        default_reason=f"{decision} via API",
    )
    if isinstance(parsed, ApiResponse):
        return parsed
    session_key = SessionId(UUID(session_id))
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(session_key)
    if session is None:
        return ApiResponse(
            status_code=404,
            body={"session_id": session_id, "memory_id": memory_id, "status": "not_found"},
        )
    memory_store = SQLiteMemoryStore(database_path)
    record = memory_store.get(MemoryId(UUID(memory_id)))
    if record is None:
        return ApiResponse(
            status_code=404,
            body={"session_id": session_id, "memory_id": memory_id, "status": "not_found"},
        )
    try:
        existing_records = tuple(memory_store.list(memory_review_scope_query(record)))
        result = MemoryReviewService().review(
            session=session,
            record=record,
            next_sequence=session.current_sequence + 1,
            command=MemoryReviewCommand(
                action=action,
                operator=parsed["operator"],
                reason=parsed["reason"],
            ),
            existing_records=existing_records,
        )
    except ValueError as error:
        return conflict(
            session_id=session_id,
            status="invalid_state",
            reason=str(error),
        )
    memory_store.upsert(result.record)
    for superseded in result.superseded_records:
        memory_store.upsert(superseded)
    SQLiteEventStore(database_path).append(result.event)
    updated_session = projection_store.save_session(apply_event(session, result.event))
    return ApiResponse(
        status_code=200,
        body={
            "session_id": session_id,
            "memory_id": memory_id,
            "decision": decision,
            "event_type": result.event.event_type.value,
            "sequence": result.event.sequence,
            "status": updated_session.status.value,
            "memory_status": result.record.status.value,
            "superseded_memory_ids": [
                str(superseded.memory_id) for superseded in result.superseded_records
            ],
        },
    )
