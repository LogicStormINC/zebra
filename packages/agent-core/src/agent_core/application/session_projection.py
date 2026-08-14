from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus


class SessionProjectionError(ValueError):
    """Raised when a session projection cannot be rebuilt from events."""


def rebuild_session(events: list[SessionEvent]) -> Session:
    if not events:
        raise SessionProjectionError("cannot rebuild session from empty event stream")

    first_event = events[0]
    if first_event.event_type is not EventType.SESSION_CREATED:
        raise SessionProjectionError("first event must be session_created")

    session = Session.create(
        title=_session_title_from_event(first_event),
        created_at=first_event.created_at,
    ).model_copy(
        update={
            "session_id": first_event.session_id,
            "current_sequence": first_event.sequence,
            "updated_at": first_event.created_at,
        }
    )

    expected_sequence = 0
    for event in events:
        if event.session_id != session.session_id:
            raise SessionProjectionError("event stream contains multiple session_ids")
        if event.sequence != expected_sequence:
            msg = f"expected event sequence {expected_sequence}, got {event.sequence}"
            raise SessionProjectionError(msg)

        session = apply_event(session, event)
        expected_sequence += 1

    return session


def apply_event(session: Session, event: SessionEvent) -> Session:
    if event.session_id != session.session_id:
        raise SessionProjectionError("event session_id does not match projection session_id")

    projected = session
    next_status = _next_status_for_event(event)
    if next_status is not None and next_status is not projected.status:
        projected = projected.transition_to(next_status, updated_at=event.created_at)

    updates: dict[str, object] = {
        "updated_at": event.created_at,
        "current_sequence": event.sequence,
    }
    approval_context = _approval_context_from_event(event)
    if approval_context is not None:
        updates["approval_context"] = approval_context
    elif event.event_type in {
        EventType.APPROVAL_GRANTED,
        EventType.APPROVAL_REJECTED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_FAILED,
        EventType.SESSION_CANCELLED,
    }:
        updates["approval_context"] = None
    clarification_context = _clarification_context_from_event(event)
    if clarification_context is not None:
        updates["clarification_context"] = clarification_context
    elif event.event_type in {
        EventType.CLARIFICATION_RESPONDED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_FAILED,
        EventType.SESSION_CANCELLED,
    }:
        updates["clarification_context"] = None
    task_plan = _task_plan_from_event(event)
    if task_plan is not None:
        updates["task_plan"] = task_plan
    if event.event_type is EventType.SESSION_TITLE_UPDATED:
        updates["title"] = _session_title_from_event(event)
    return projected.model_copy(update=updates)


def _session_title_from_event(event: SessionEvent) -> str:
    title = event.payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SessionProjectionError("session_created event payload must include a title")
    return title


def _next_status_for_event(event: SessionEvent) -> SessionStatus | None:
    status_map: dict[EventType, SessionStatus] = {
        EventType.TASK_PREPARED: SessionStatus.READY,
        EventType.HARNESS_ATTEMPT_STARTED: SessionStatus.RUNNING,
        EventType.ATTEMPT_CONTINUATION_STARTED: SessionStatus.RUNNING,
        EventType.ATTEMPT_OUTCOME_RECORDED: SessionStatus.RUNNING,
        EventType.MODEL_REQUEST_STARTED: SessionStatus.RUNNING,
        EventType.MODEL_RESPONSE_DELTA: SessionStatus.RUNNING,
        EventType.PLAN_PROPOSED: SessionStatus.RUNNING,
        EventType.PLAN_APPROVED: SessionStatus.RUNNING,
        EventType.TOOL_CALL_PROPOSED: SessionStatus.RUNNING,
        EventType.TOOL_EXECUTION_STARTED: SessionStatus.RUNNING,
        EventType.APPROVAL_REQUESTED: SessionStatus.WAITING_APPROVAL,
        EventType.APPROVAL_GRANTED: SessionStatus.RUNNING,
        EventType.APPROVAL_REJECTED: SessionStatus.FAILED,
        EventType.CLARIFICATION_REQUESTED: SessionStatus.WAITING_INPUT,
        EventType.CLARIFICATION_RESPONDED: SessionStatus.READY,
        EventType.SESSION_SUSPENDED: SessionStatus.SUSPENDED,
        EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED: SessionStatus.SUSPENDED,
        EventType.SESSION_RESUMED: SessionStatus.READY,
        EventType.SESSION_COMPLETED: SessionStatus.COMPLETED,
        EventType.SESSION_FAILED: SessionStatus.FAILED,
        EventType.SESSION_CANCELLED: SessionStatus.CANCELLED,
    }
    return status_map.get(event.event_type)


def _approval_context_from_event(event: SessionEvent) -> ApprovalContext | None:
    if event.event_type is not EventType.APPROVAL_REQUESTED:
        return None
    tool_name = _optional_payload_string(event, "tool_name")
    reason = _optional_payload_string(event, "reason")
    policy_profile = _optional_payload_string(event, "policy_profile")
    if tool_name is None or reason is None or policy_profile is None:
        return None
    return ApprovalContext(
        tool_name=tool_name,
        reason=reason,
        policy_profile=policy_profile,
        route=_optional_payload_string(event, "route"),
        target=_optional_payload_string(event, "target"),
        network_profile=_optional_payload_string(event, "network_profile"),
        scope=_payload_scope(event),
        tool_call_id=_optional_payload_string(event, "tool_call_id"),
        provider_call_id=_optional_payload_string(event, "provider_call_id"),
        provider_tool_name=_optional_payload_string(event, "provider_tool_name"),
        provider_arguments=_payload_provider_arguments(event),
        arguments=_payload_arguments(event),
        assistant_message=_optional_payload_string(event, "assistant_message"),
        call_fingerprint=_optional_payload_string(event, "call_fingerprint"),
    )


def _clarification_context_from_event(event: SessionEvent) -> ClarificationContext | None:
    if event.event_type is not EventType.CLARIFICATION_REQUESTED:
        return None
    try:
        return ClarificationContext.model_validate(
            {
                "clarification_id": event.payload.get("clarification_id"),
                "tool_call_id": event.payload.get("tool_call_id"),
                "provider_call_id": event.payload.get("provider_call_id"),
                "question": event.payload.get("question"),
                "choices": event.payload.get("choices", ()),
                "context": event.payload.get("context"),
                "assistant_message": event.payload.get("assistant_message"),
                "requested_at": event.created_at,
                "response_schema": event.payload.get("response_schema"),
                "elicitation_source": event.payload.get("elicitation_source"),
            }
        )
    except ValueError:
        return None


def _task_plan_from_event(event: SessionEvent) -> SessionPlan | None:
    if event.event_type is not EventType.PLAN_UPDATED:
        return None
    try:
        return SessionPlan.model_validate(
            {"steps": event.payload.get("steps", ()), "updated_at": event.created_at}
        )
    except ValueError as exc:
        raise SessionProjectionError("plan_updated event payload is invalid") from exc


def _optional_payload_string(event: SessionEvent, key: str) -> str | None:
    value = event.payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _payload_scope(event: SessionEvent) -> tuple[str, ...]:
    scope = event.payload.get("scope")
    if not isinstance(scope, list | tuple):
        return ()
    return tuple(item for item in scope if isinstance(item, str) and item.strip())


def _payload_arguments(event: SessionEvent) -> dict[str, object]:
    value = event.payload.get("arguments")
    return dict(value) if isinstance(value, dict) else {}


def _payload_provider_arguments(event: SessionEvent) -> dict[str, object]:
    value = event.payload.get("provider_arguments")
    return dict(value) if isinstance(value, dict) else {}
