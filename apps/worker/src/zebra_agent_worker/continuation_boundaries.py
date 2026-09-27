"""Durable boundaries proving that a recovered continuation was consumed."""

from agent_core.domain.events import EventType, SessionEvent

_ATTEMPT_RESULT_BOUNDARIES = frozenset(
    {
        EventType.APPROVAL_REQUESTED,
        EventType.CLARIFICATION_REQUESTED,
        EventType.SESSION_SUSPENDED,
        EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
        EventType.TURN_COMPLETED,
        EventType.TURN_FAILED,
        EventType.TURN_CANCELLED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_FAILED,
        EventType.SESSION_CANCELLED,
    }
)


def has_later_attempt_result_boundary(
    events: list[SessionEvent], *, after_index: int
) -> bool:
    """Return whether a later durable event proves the attempt produced an outcome."""

    return any(
        event.event_type in _ATTEMPT_RESULT_BOUNDARIES
        for event in events[after_index + 1 :]
    )
