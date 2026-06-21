from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.sessions import Session, SessionStatus


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

    return projected.model_copy(
        update={
            "updated_at": event.created_at,
            "current_sequence": event.sequence,
        }
    )


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
        EventType.SESSION_COMPLETED: SessionStatus.COMPLETED,
        EventType.SESSION_FAILED: SessionStatus.FAILED,
        EventType.SESSION_CANCELLED: SessionStatus.CANCELLED,
    }
    return status_map.get(event.event_type)
