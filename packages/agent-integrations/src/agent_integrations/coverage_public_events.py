"""Strict public output is progress, not arbitrary candidate/model/tool text."""

from collections.abc import Iterable

from agent_core.domain.events import EventType, SessionEvent

_PROGRESS = frozenset(
    {
        EventType.COVERAGE_MANIFEST_COMMITTED,
        EventType.COVERAGE_BATCH_ACCEPTED,
        EventType.COVERAGE_RUN_CANCELLED,
        EventType.COVERAGE_REPORT_CERTIFIED,
    }
)
_LIFECYCLE = frozenset(
    {
        EventType.TURN_COMPLETED,
        EventType.TURN_CANCELLED,
        EventType.TURN_FAILED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_CANCELLED,
        EventType.SESSION_FAILED,
        EventType.SESSION_SUSPENDED,
    }
)


def strict_coverage_events(events: Iterable[SessionEvent]) -> bool:
    """Presence is fail-closed even if a historical admission is malformed."""
    return any(
        (event.event_type is EventType.TASK_PREPARED and "coverage_admission" in event.payload)
        or event.event_type in _PROGRESS
        for event in events
    )


def coverage_projection_event(event: SessionEvent, *, strict: bool) -> SessionEvent | None:
    """Only the typed AG-UI projector may consume private progress bindings.

    Historical certification does not release any free-text answer, tool output,
    content.present attachment or Artifact. Download authorization is separate.
    """
    if not strict or event.event_type in _PROGRESS:
        return event
    if event.event_type in _LIFECYCLE:
        return event.model_copy(update={"payload": {"reason": "coverage_execution_ended"}})
    if event.event_type is EventType.USER_MESSAGE_RECEIVED:
        turn_id = event.payload.get("turn_id")
        payload = {"turn_id": turn_id} if type(turn_id) is str and len(turn_id) <= 512 else {}
        return event.model_copy(update={"payload": payload})
    return None
