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

from zebra_agent_api.memory_review_serialization import (
    _bulk_outcome,
    _not_found_response,
    _review_response_body,
    _scope_matches,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_payloads import (
    parse_approval_decision_payload,
    parse_bulk_memory_review_payload,
)


def _review_memory(
    *,
    database_path: Path,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> ApiResponse:
    parsed = parse_approval_decision_payload(
        payload,
        default_reason=f"{decision} via API",
    )
    if isinstance(parsed, ApiResponse):
        return parsed
    memory_store = SQLiteMemoryStore(database_path)
    record = memory_store.get(MemoryId(UUID(memory_id)))
    if record is None or not _scope_matches(record, expected_visibility, expected_scope_id):
        return _not_found_response(
            memory_id=memory_id,
            visibility=expected_visibility,
            scope_id=expected_scope_id,
        )
    if record.source_session_id is None:
        return _not_found_response(
            memory_id=memory_id,
            visibility=expected_visibility,
            scope_id=expected_scope_id,
        )
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(record.source_session_id)
    if session is None:
        return _not_found_response(
            memory_id=memory_id,
            visibility=expected_visibility,
            scope_id=expected_scope_id,
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
            session_id=(
                expected_scope_id
                if expected_visibility is MemoryVisibility.REPO
                else str(session.session_id)
            ),
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
        body=_review_response_body(
            session_id=str(updated_session.session_id),
            memory_id=memory_id,
            decision=decision,
            result=result,
            session_status=updated_session.status.value,
            visibility=expected_visibility,
            scope_id=expected_scope_id,
        ),
    )


def _review_memory_bulk(
    *,
    database_path: Path,
    payload: dict[str, object],
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> ApiResponse:
    parsed = parse_bulk_memory_review_payload(payload)
    if isinstance(parsed, ApiResponse):
        return parsed
    action = (
        MemoryReviewAction.CONFIRM if parsed["decision"] == "confirm" else MemoryReviewAction.EXPIRE
    )
    return _review_memory_ids(
        database_path=database_path,
        memory_ids=parsed["memory_ids"],
        action=action,
        decision=parsed["decision"],
        operator=parsed["operator"],
        reason=parsed["reason"],
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )


def _review_memory_queue(
    *,
    database_path: Path,
    payload: dict[str, object],
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> ApiResponse:
    parsed = parse_approval_decision_payload(
        payload,
        default_reason="queue sweep via API",
    )
    if isinstance(parsed, ApiResponse):
        return parsed
    decision = payload.get("decision")
    if decision not in {"confirm", "expire"}:
        return conflict(
            session_id=expected_scope_id,
            status="invalid_request",
            reason="decision must be either 'confirm' or 'expire'",
        )
    action = MemoryReviewAction.CONFIRM if decision == "confirm" else MemoryReviewAction.EXPIRE
    memory_ids = _queued_memory_ids(
        database_path=database_path,
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )
    response = _review_memory_ids(
        database_path=database_path,
        memory_ids=memory_ids,
        action=action,
        decision=decision,
        operator=parsed["operator"],
        reason=parsed["reason"],
        expected_visibility=expected_visibility,
        expected_scope_id=expected_scope_id,
    )
    response.body["status"] = "ok"
    response.body["queue_sweep"] = True
    response.body["queued_count"] = len(memory_ids)
    return response


def _review_memory_ids(
    *,
    database_path: Path,
    memory_ids: list[str],
    action: MemoryReviewAction,
    decision: str,
    operator: str,
    reason: str,
    expected_visibility: MemoryVisibility,
    expected_scope_id: str,
) -> ApiResponse:
    shared_payload = {"operator": operator, "reason": reason}
    seen_memory_ids: set[str] = set()
    results: list[dict[str, object]] = []
    applied_count = 0
    skipped_count = 0
    invalid_count = 0

    for memory_id in memory_ids:
        if memory_id in seen_memory_ids:
            results.append(
                _bulk_outcome(
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
                _bulk_outcome(
                    memory_id=memory_id,
                    outcome="invalid",
                    status="invalid_id",
                    reason="memory_id must be a valid UUID",
                )
            )
            invalid_count += 1
            continue
        response = _review_memory(
            database_path=database_path,
            memory_id=memory_id,
            payload=dict(shared_payload),
            action=action,
            decision=decision,
            expected_visibility=expected_visibility,
            expected_scope_id=expected_scope_id,
        )
        if response.status_code == 200:
            results.append({"outcome": "applied", **response.body})
            applied_count += 1
            continue
        if response.status_code == 404:
            results.append(
                _bulk_outcome(
                    memory_id=memory_id,
                    outcome="skipped",
                    status="not_found",
                )
            )
            skipped_count += 1
            continue
        reason_value = response.body.get("reason")
        results.append(
            _bulk_outcome(
                memory_id=memory_id,
                outcome="invalid",
                status=str(response.body.get("status", "invalid_state")),
                reason=reason_value if isinstance(reason_value, str) else None,
            )
        )
        invalid_count += 1

    body: dict[str, object] = {
        "decision": decision,
        "total_requested": len(memory_ids),
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "invalid_count": invalid_count,
        "results": results,
    }
    if expected_visibility is MemoryVisibility.REPO:
        body["session_id"] = expected_scope_id
    elif expected_visibility is MemoryVisibility.USER:
        body["user_id"] = expected_scope_id
    else:
        body["tenant_id"] = expected_scope_id
    return ApiResponse(status_code=200, body=body)


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
