from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.domain.context_capsule import ContextCapsule, PendingToolState
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_identity_read import _parse_session_id


class SessionContextControlApi:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def inspect(self, session_id: str) -> ApiResponse:
        resolved = self._resolve(session_id)
        if isinstance(resolved, ApiResponse):
            return resolved
        _, events = resolved
        compacted = [event for event in events if event.event_type is EventType.CONTEXT_COMPACTED]
        latest = compacted[-1] if compacted else None
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "compaction_count": len(compacted),
                "latest": latest.payload if latest is not None else None,
                "continuation": {
                    "mode": "capsule_fallback",
                    "provider_native": False,
                    "authority": "session_events",
                },
            },
        )

    def compact(self, session_id: str) -> ApiResponse:
        resolved = self._resolve(session_id)
        if isinstance(resolved, ApiResponse):
            return resolved
        session, events = resolved
        if session.status is SessionStatus.RUNNING:
            return conflict(
                session_id=session_id,
                status="context_busy",
                reason="manual compaction requires a non-running session boundary",
            )
        capsule = _capsule_from_events(events, created_at=datetime.now(UTC))
        before = _estimate_tokens([event.payload for event in events])
        after = _estimate_tokens(capsule.model_dump(mode="json"))
        event = SessionEvent.create(
            session_id=session.session_id,
            sequence=session.current_sequence + 1,
            event_type=EventType.CONTEXT_COMPACTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": _latest_attempt(events),
                "before_tokens": before,
                "after_tokens": after,
                "removed_message_count": 0,
                "retained_message_count": 1,
                "within_budget": True,
                "provenance": "manual_event_projection_compaction",
                "capsule": capsule.model_dump(mode="json"),
            },
            idempotency_key=f"manual-context-compact:{capsule.source_hash}",
            created_at=capsule.created_at,
        )
        stored = SQLiteEventStore(self._database_path).append(event)
        SQLiteProjectionStore(self._database_path).save_session(apply_event(session, stored))
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "compacted",
                "sequence": stored.sequence,
                "before_tokens": before,
                "after_tokens": after,
                "capsule": capsule.model_dump(mode="json"),
            },
        )

    def _resolve(
        self,
        session_id: str,
    ) -> tuple[Session, list[SessionEvent]] | ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self._database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = SQLiteEventStore(self._database_path).list_for_session(session_key)
        return session, events


def _capsule_from_events(
    events: list[SessionEvent],
    *,
    created_at: datetime,
) -> ContextCapsule:
    objective = next(
        (
            str(event.payload["content"])
            for event in reversed(events)
            if event.event_type is EventType.USER_MESSAGE_RECEIVED
            and isinstance(event.payload.get("content"), str)
        ),
        "Continue the session task.",
    )
    decisions = tuple(
        str(event.payload["assistant_message"])[:1_000]
        for event in events
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
        and isinstance(event.payload.get("assistant_message"), str)
    )[-8:]
    plans = tuple(
        str(event.payload.get("summary", ""))[:1_000]
        for event in events
        if event.event_type in {EventType.PLAN_PROPOSED, EventType.PLAN_UPDATED}
        and str(event.payload.get("summary", "")).strip()
    )[-8:]
    tests = tuple(
        str(event.payload.get("summary", ""))[:1_000]
        for event in events
        if event.event_type is EventType.TESTS_COMPLETED
    )[-5:]
    errors = tuple(
        str(event.payload.get("output", event.payload.get("summary", "")))[:1_000]
        for event in events
        if event.event_type in {EventType.TOOL_EXECUTION_FAILED, EventType.SESSION_FAILED}
    )[-5:]
    pending = _pending_tool(events)
    encoded = json.dumps(
        [event.model_dump(mode="json") for event in events],
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    source_hash = sha256(encoded).hexdigest()
    return ContextCapsule(
        capsule_id=f"ctxcap-{source_hash[:24]}",
        objective=objective,
        constraints=(objective,),
        decisions=decisions,
        plan=plans,
        tests=tests,
        errors=errors,
        pending_tools=(pending,) if pending is not None else (),
        immediate_next=plans[-1] if plans else decisions[-1] if decisions else objective,
        source_hash=source_hash,
        confidence=0.85,
        created_at=created_at,
    )


def _pending_tool(events: list[SessionEvent]) -> PendingToolState | None:
    pending: PendingToolState | None = None
    for event in events:
        if event.event_type is EventType.APPROVAL_REQUESTED:
            call_id = event.payload.get("provider_call_id") or event.payload.get("tool_call_id")
            name = event.payload.get("tool_name")
            arguments = event.payload.get("arguments")
            if isinstance(call_id, str) and isinstance(name, str):
                pending = PendingToolState(
                    call_id=call_id,
                    name=name,
                    arguments=dict(arguments) if isinstance(arguments, dict) else {},
                )
        elif event.event_type in {EventType.APPROVAL_GRANTED, EventType.APPROVAL_REJECTED}:
            pending = None
    return pending


def _latest_attempt(events: list[SessionEvent]) -> int:
    for event in reversed(events):
        value = event.payload.get("attempt_number")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return 1


def _estimate_tokens(value: object) -> int:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return max(1, (len(encoded) + 3) // 4)
