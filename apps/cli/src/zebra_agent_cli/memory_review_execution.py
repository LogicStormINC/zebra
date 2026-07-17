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
from agent_core.domain.memories import MemoryQuery, MemoryRecord, MemoryStatus, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_api.session_context import session_workspace_root

from zebra_agent_cli.memory_review_serialization import (
    _bulk_outcome_payload,
    _not_found_payload,
    _scope_matches,
)


def _record_memory_review(
    *,
    database_path: Path,
    memory_id: str,
    decision: str,
    operator: str,
    reason: str,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> dict[str, object]:
    memory_store = SQLiteMemoryStore(database_path)
    record = memory_store.get(MemoryId(UUID(memory_id)))
    if record is None or not _scope_matches(record, expected_visibility, expected_scope_id):
        return _not_found_payload(
            database_path=database_path,
            memory_id=memory_id,
            visibility=expected_visibility,
            scope_id=expected_scope_id,
        )
    if record.source_session_id is None:
        return _not_found_payload(
            database_path=database_path,
            memory_id=memory_id,
            visibility=expected_visibility,
            scope_id=expected_scope_id,
        )
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(record.source_session_id)
    if session is None:
        return _not_found_payload(
            database_path=database_path,
            memory_id=memory_id,
            visibility=expected_visibility,
            scope_id=expected_scope_id,
        )
    action = MemoryReviewAction.CONFIRM if decision == "confirm" else MemoryReviewAction.EXPIRE
    try:
        existing_records = tuple(memory_store.list(memory_review_scope_query(record)))
        result = MemoryReviewService().review(
            session=session,
            record=record,
            next_sequence=session.current_sequence + 1,
            command=MemoryReviewCommand(
                action=action,
                operator=operator,
                reason=reason or f"{decision} via CLI",
            ),
            existing_records=existing_records,
        )
    except ValueError as error:
        error_payload: dict[str, object] = {
            "session_id": (
                expected_scope_id
                if expected_visibility is MemoryVisibility.REPO
                else str(session.session_id)
            ),
            "memory_id": memory_id,
            "database": str(database_path),
            "status": "invalid_state",
            "reason": str(error),
        }
        if expected_visibility is MemoryVisibility.USER:
            error_payload["user_id"] = expected_scope_id
        elif expected_visibility is MemoryVisibility.TENANT:
            error_payload["tenant_id"] = expected_scope_id
        return error_payload
    memory_store.upsert(result.record)
    for superseded in result.superseded_records:
        memory_store.upsert(superseded)
    SQLiteEventStore(database_path).append(result.event)
    updated_session = projection_store.save_session(apply_event(session, result.event))
    payload: dict[str, object] = {
        "session_id": str(updated_session.session_id),
        "memory_id": memory_id,
        "database": str(database_path),
        "decision": decision,
        "event_type": result.event.event_type.value,
        "sequence": result.event.sequence,
        "status": updated_session.status.value,
        "memory_status": result.record.status.value,
        "superseded_memory_ids": [
            str(superseded.memory_id) for superseded in result.superseded_records
        ],
        "duplicate_of_memory_id": (
            None if result.duplicate_of is None else str(result.duplicate_of.memory_id)
        ),
    }
    if expected_visibility is MemoryVisibility.USER:
        payload["user_id"] = expected_scope_id
    elif expected_visibility is MemoryVisibility.TENANT:
        payload["tenant_id"] = expected_scope_id
    return payload


def _record_bulk_memory_review(
    *,
    database_path: Path,
    memory_ids: list[str],
    decision: str,
    operator: str,
    reason: str,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> dict[str, object]:
    return _record_memory_ids(
        database_path=database_path,
        memory_ids=memory_ids,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )


def _record_queue_memory_review(
    *,
    database_path: Path,
    decision: str,
    operator: str,
    reason: str,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> dict[str, object]:
    memory_ids = _queued_memory_ids(
        database_path=database_path,
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )
    payload = _record_memory_ids(
        database_path=database_path,
        memory_ids=memory_ids,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )
    payload["status"] = "ok"
    payload["queue_sweep"] = True
    payload["queued_count"] = len(memory_ids)
    return payload


def _record_memory_ids(
    *,
    database_path: Path,
    memory_ids: list[str],
    decision: str,
    operator: str,
    reason: str,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> dict[str, object]:
    seen_memory_ids: set[str] = set()
    results: list[dict[str, object]] = []
    applied_count = 0
    skipped_count = 0
    invalid_count = 0

    for memory_id in memory_ids:
        if memory_id in seen_memory_ids:
            results.append(
                _bulk_outcome_payload(
                    memory_id=memory_id,
                    outcome="skipped",
                    status="duplicate_request",
                    reason="memory_id was requested more than once",
                )
            )
            skipped_count += 1
            continue
        seen_memory_ids.add(memory_id)
        try:
            UUID(memory_id)
        except ValueError:
            results.append(
                _bulk_outcome_payload(
                    memory_id=memory_id,
                    outcome="invalid",
                    status="invalid_id",
                    reason="memory_id must be a valid UUID",
                )
            )
            invalid_count += 1
            continue
        payload = _record_memory_review(
            database_path=database_path,
            memory_id=memory_id,
            decision=decision,
            operator=operator,
            reason=reason,
            expected_visibility=expected_visibility,
            expected_scope_id=expected_scope_id,
        )
        status = payload.get("status")
        if status == "not_found":
            results.append(
                _bulk_outcome_payload(
                    memory_id=memory_id,
                    outcome="skipped",
                    status="not_found",
                )
            )
            skipped_count += 1
            continue
        if status == "invalid_state":
            reason_value = payload.get("reason")
            results.append(
                _bulk_outcome_payload(
                    memory_id=memory_id,
                    outcome="invalid",
                    status="invalid_state",
                    reason=reason_value if isinstance(reason_value, str) else None,
                )
            )
            invalid_count += 1
            continue
        results.append({"outcome": "applied", **payload})
        applied_count += 1

    response: dict[str, object] = {
        "database": str(database_path),
        "decision": decision,
        "total_requested": len(memory_ids),
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "invalid_count": invalid_count,
        "results": results,
    }
    if expected_visibility is MemoryVisibility.REPO:
        response["session_id"] = expected_scope_id
    elif expected_visibility is MemoryVisibility.USER:
        response["user_id"] = expected_scope_id
    else:
        response["tenant_id"] = expected_scope_id
    return response


def _queued_memory_ids(
    *,
    database_path: Path,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> list[str]:
    return [
        str(record.memory_id)
        for record in _queued_memory_records(
            database_path=database_path,
            expected_visibility=expected_visibility,
            expected_scope_id=expected_scope_id,
        )
    ]


def _queued_memory_records(
    *,
    database_path: Path,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> list[MemoryRecord]:
    memory_store = SQLiteMemoryStore(database_path)
    if expected_visibility is MemoryVisibility.REPO:
        session_key = SessionId(UUID(expected_scope_id))
        session = SQLiteProjectionStore(database_path).get_session(session_key)
        if session is None:
            return []
        events = list(SQLiteEventStore(database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return []
        return memory_store.list(
            MemoryQuery(
                repo_id=str(workspace_root),
                source_session_id=session_key,
                visibility=MemoryVisibility.REPO,
                statuses=(MemoryStatus.CANDIDATE,),
                limit=500,
            )
        )
    if expected_visibility is MemoryVisibility.USER:
        return memory_store.list(
            MemoryQuery(
                user_id=expected_scope_id,
                visibility=MemoryVisibility.USER,
                statuses=(MemoryStatus.CANDIDATE,),
                limit=500,
            )
        )
    return memory_store.list(
        MemoryQuery(
            tenant_id=expected_scope_id,
            visibility=MemoryVisibility.TENANT,
            statuses=(MemoryStatus.CANDIDATE,),
            limit=500,
        )
    )
