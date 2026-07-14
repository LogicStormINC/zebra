from agent_core.domain.events import EventType, SessionEvent
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
        EventType.MODEL_REQUEST_STARTED: SessionStatus.RUNNING,
        EventType.PLAN_PROPOSED: SessionStatus.RUNNING,
        EventType.PLAN_APPROVED: SessionStatus.RUNNING,
        EventType.TOOL_CALL_PROPOSED: SessionStatus.RUNNING,
        EventType.TOOL_EXECUTION_STARTED: SessionStatus.RUNNING,
        EventType.APPROVAL_REQUESTED: SessionStatus.WAITING_APPROVAL,
        EventType.APPROVAL_GRANTED: SessionStatus.RUNNING,
        EventType.APPROVAL_REJECTED: SessionStatus.FAILED,
        EventType.SESSION_SUSPENDED: SessionStatus.SUSPENDED,
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
        arguments=_payload_arguments(event),
        assistant_message=_optional_payload_string(event, "assistant_message"),
        call_fingerprint=_optional_payload_string(event, "call_fingerprint"),
    )


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
