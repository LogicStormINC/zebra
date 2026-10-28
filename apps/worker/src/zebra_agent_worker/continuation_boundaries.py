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


def current_continuation_events(
    events: list[SessionEvent], *, waiting_children: bool = False
) -> list[SessionEvent]:
    """Discard superseded work even when its receipt preceded the start marker."""
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if (
            event.event_type in {
                EventType.USER_MESSAGE_RECEIVED,
                EventType.TURN_COMPLETED, EventType.TURN_FAILED, EventType.TURN_CANCELLED,
                EventType.SESSION_COMPLETED, EventType.SESSION_FAILED,
                EventType.SESSION_CANCELLED, EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
                EventType.APPROVAL_REJECTED,
            }
            or (
                event.event_type is EventType.SESSION_SUSPENDED
                and not (waiting_children and event.payload.get("reason") == "waiting_children")
            )
            or (
                event.event_type is EventType.SESSION_COMMAND_ACCEPTED
                and event.payload.get("kind") in {"stop", "cancel", "suspend"}
            )
        ):
            return events[index + 1 :]
    return events


def has_later_attempt_result_boundary(
    events: list[SessionEvent], *, after_index: int
) -> bool:
    """Return whether a later durable event proves the attempt produced an outcome."""

    return any(
        event.event_type in _ATTEMPT_RESULT_BOUNDARIES
        for event in events[after_index + 1 :]
    )
