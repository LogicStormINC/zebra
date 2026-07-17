from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextSourceEventRange,
    PendingToolState,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import (
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
)

from zebra_agent_api.responses import ApiResponse, bad_request, conflict
from zebra_agent_api.session_context_inspection import (
    context_occupancy as _context_occupancy,
)
from zebra_agent_api.session_context_inspection import estimate_tokens as _estimate_tokens
from zebra_agent_api.session_identity_read import _parse_session_id


class SessionContextControlApi:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def inspect(self, session_id: str) -> ApiResponse:
        resolved = self._resolve(session_id)
        if isinstance(resolved, ApiResponse):
            return resolved
        session, events = resolved
        compacted = [event for event in events if event.event_type is EventType.CONTEXT_COMPACTED]
        latest = compacted[-1] if compacted else None
        active = SQLiteContextLifecycleStore(self._database_path).get_active_capsule(
            session.session_id
        )
        latest_payload = dict(latest.payload) if latest is not None else None
        if latest_payload is not None and active is not None:
            latest_payload["capsule"] = active.capsule.model_dump(mode="json")
            latest_payload["capsule_artifact_id"] = str(active.artifact_id)
        occupancy = _context_occupancy(events, latest)
        continuation = next(
            (
                event.payload
                for event in reversed(events)
                if event.event_type is EventType.CONTEXT_CONTINUATION_SELECTED
            ),
            None,
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "compaction_count": len(compacted),
                "latest": latest_payload,
                "occupancy": occupancy,
                "state": {
                    "retained": occupancy["retained_event_count"],
                    "folded": sum(
                        int(event.payload.get("removed_message_count", 0))
                        for event in compacted
                    ),
                    "artifact_backed": occupancy["artifact_reference_count"],
                    "historical_capsules": [
                        str(event.payload["capsule_id"])
                        for event in events
                        if event.event_type is EventType.CONTEXT_CAPSULE_CREATED
                    ],
                },
                "continuation": {
                    "mode": (
                        continuation.get("mode", "capsule_fallback")
                        if continuation is not None
                        else "capsule_fallback"
                    ),
                    "provider_native": (
                        continuation is not None
                        and continuation.get("mode") == "provider_native"
                    ),
                    "authority": "session_events_and_capsule_artifact",
                    "reason": continuation.get("reason") if continuation else None,
                    "artifact_id": (
                        continuation.get("artifact_id") if continuation else None
                    ),
                },
            },
        )

    def compact(
        self, session_id: str, body: Mapping[str, object] | None = None
    ) -> ApiResponse:
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
        options = body or {}
        focus = _optional_focus(options.get("focus"))
        if isinstance(focus, ApiResponse):
            return focus
        preview = options.get("preview", False)
        if not isinstance(preview, bool):
            return bad_request("preview must be a boolean")
        through_sequence = _through_sequence(options.get("through_sequence"), events)
        if isinstance(through_sequence, ApiResponse):
            return through_sequence
        source_events = (
            [event for event in events if event.sequence <= through_sequence]
            if through_sequence is not None
            else events
        )
        tail_events = (
            [event for event in events if event.sequence > through_sequence]
            if through_sequence is not None
            else []
        )
        if len(tail_events) > 32:
            return bad_request(
                "through_sequence leaves more than 32 exact tail events; choose a later boundary"
            )
        capsule = _capsule_from_events(
            source_events, created_at=datetime.now(UTC), focus=focus
        )
        if tail_events:
            capsule = capsule.model_copy(
                update={
                    "recent_exact_tail_refs": tuple(
                        f"event://{session_id}/{event.sequence}" for event in tail_events
                    )
                }
            )
        before = _estimate_tokens([event.payload for event in events])
        after = _estimate_tokens(capsule.model_dump(mode="json"))
        if preview:
            return ApiResponse(
                status_code=200,
                body={
                    "session_id": session_id,
                    "status": "preview",
                    "before_tokens": before,
                    "after_tokens": after,
                    "focus": focus,
                    "through_sequence": through_sequence,
                    "would_retain": list(capsule.model_dump(mode="json")),
                    "would_fold_event_count": max(0, len(events) - 1),
                    "capsule": capsule.model_dump(mode="json"),
                },
            )
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
                "focus": focus,
                "through_sequence": through_sequence,
            },
            idempotency_key=f"manual-context-compact:{capsule.source_hash}",
            created_at=capsule.created_at,
        )
        lifecycle = SQLiteContextLifecycleStore(self._database_path)
        active = lifecycle.get_active_capsule(session.session_id)
        if capsule.source_event_range is None:
            raise ValueError("manual capsule source range is required")
        stored = lifecycle.persist_capsule_and_advance(
            session_id=session.session_id,
            capsule=capsule,
            validation_context=ContextCapsuleValidationContext(
                expected_source_hash=capsule.source_hash,
                expected_source_event_range=capsule.source_event_range,
                unresolved_tool_call_ids=frozenset(
                    tool.call_id for tool in capsule.pending_tools
                ),
                protected_user_constraints=frozenset(
                    capsule.protected_user_constraints
                ),
                approval_and_policy_state=frozenset(
                    capsule.approvals_and_policy_state
                ),
                readable_artifact_refs=frozenset(
                    (*capsule.artifact_refs, *capsule.recent_exact_tail_refs)
                ),
            ),
            sequence=event.sequence,
            expected_active_capsule_id=active.capsule.capsule_id if active else None,
            compaction_event=event,
            created_at=capsule.created_at,
        )
        projection = apply_event(apply_event(session, event), stored.event)
        SQLiteProjectionStore(self._database_path).save_session(projection)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "compacted",
                "sequence": stored.event.sequence,
                "artifact_id": str(stored.artifact_id),
                "before_tokens": before,
                "after_tokens": after,
                "capsule": capsule.model_dump(mode="json"),
                "focus": focus,
                "through_sequence": through_sequence,
            },
        )

    def recover(self, session_id: str, body: Mapping[str, object]) -> ApiResponse:
        resolved = self._resolve(session_id)
        if isinstance(resolved, ApiResponse):
            return resolved
        session, events = resolved
        if session.status is SessionStatus.RUNNING:
            return conflict(
                session_id=session_id,
                status="context_busy",
                reason="context recovery requires a non-running session boundary",
            )
        capsule_id = body.get("capsule_id")
        if not isinstance(capsule_id, str) or not capsule_id.strip():
            return bad_request("capsule_id must be a non-blank string")
        lifecycle = SQLiteContextLifecycleStore(self._database_path)
        stored_capsule = lifecycle.get_capsule(capsule_id.strip())
        if stored_capsule is None or stored_capsule.session_id != session.session_id:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "capsule_not_found",
                    "capsule_id": capsule_id.strip(),
                },
            )
        capsule = stored_capsule.capsule
        event = SessionEvent.create(
            session_id=session.session_id,
            sequence=session.current_sequence + 1,
            event_type=EventType.CONTEXT_COMPACTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": _latest_attempt(events),
                "before_tokens": _estimate_tokens([event.payload for event in events]),
                "after_tokens": _estimate_tokens(capsule.model_dump(mode="json")),
                "removed_message_count": 0,
                "retained_message_count": 1,
                "within_budget": True,
                "provenance": "historical_capsule_recovery",
                "capsule": capsule.model_dump(mode="json"),
                "recovered_from_capsule_id": capsule.capsule_id,
            },
            idempotency_key=f"context-recover:{capsule.capsule_id}:{session.current_sequence + 1}",
            created_at=datetime.now(UTC),
        )
        active = lifecycle.get_active_capsule(session.session_id)
        lifecycle.activate_capsule(
            session_id=session.session_id,
            capsule_id=capsule.capsule_id,
            expected_active_capsule_id=active.capsule.capsule_id if active else None,
            event=event,
        )
        SQLiteProjectionStore(self._database_path).save_session(apply_event(session, event))
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "recovered",
                "sequence": event.sequence,
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
    focus: str | None = None,
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
    artifact_refs = tuple(
        sorted(
            {
                uri
                for event in events
                if isinstance(event.payload.get("metadata"), dict)
                for uri in [event.payload["metadata"].get("artifact_uri")]
                if isinstance(uri, str) and uri.strip()
            }
        )
    )
    pending = _pending_tool(events)
    encoded = json.dumps(
        [event.model_dump(mode="json") for event in events],
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    source_hash = sha256(encoded).hexdigest()
    source_range = ContextSourceEventRange(
        start_sequence=events[0].sequence,
        end_sequence=events[-1].sequence,
    )
    approvals = tuple(
        _approval_state(event)
        for event in events
        if event.event_type
        in {
            EventType.POLICY_DECISION_MADE,
            EventType.APPROVAL_REQUESTED,
            EventType.APPROVAL_GRANTED,
            EventType.APPROVAL_REJECTED,
        }
    )
    return ContextCapsule(
        capsule_id=f"ctxcap-{source_hash[:24]}",
        objective=objective,
        constraints=(objective,) + ((f"Compaction focus: {focus}",) if focus else ()),
        protected_user_constraints=(objective,),
        decisions=decisions,
        plan=plans,
        tests=tests,
        errors=errors,
        pending_tools=(pending,) if pending is not None else (),
        artifact_refs=artifact_refs,
        approvals_and_policy_state=approvals,
        immediate_next=plans[-1] if plans else decisions[-1] if decisions else objective,
        source_event_range=source_range,
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


def _approval_state(event: SessionEvent) -> str:
    detail = event.payload.get("decision", event.payload.get("reason", "recorded"))
    return f"{event.event_type.value}:{detail}"


def _optional_focus(value: object) -> str | None | ApiResponse:
    if value is None:
        return None
    if not isinstance(value, str):
        return bad_request("focus must be a string")
    normalized = value.strip()
    if not normalized:
        return bad_request("focus must not be blank")
    if len(normalized) > 500:
        return bad_request("focus must not exceed 500 characters")
    return normalized


def _through_sequence(
    value: object,
    events: list[SessionEvent],
) -> int | None | ApiResponse:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        return bad_request("through_sequence must be an integer")
    if not events or value < events[0].sequence or value > events[-1].sequence:
        return bad_request("through_sequence is outside the session event range")
    return value
