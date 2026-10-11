"""Shared Task API response shapes."""

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.domain.session_handoff import HandoffActorKind
from agent_core.ports.agent_tasks import TaskEvent

from zebra_agent_api.responses import ApiResponse

DEFAULT_TASK_LIMIT = 50
MAX_TASK_LIMIT = 100


def parse_task_limit(raw: str | None) -> int | ApiResponse:
    try:
        limit = DEFAULT_TASK_LIMIT if raw is None else int(raw)
    except ValueError:
        limit = 0
    if 1 <= limit <= MAX_TASK_LIMIT:
        return limit
    return ApiResponse(
        400,
        {"status": "invalid_request", "reason": "limit must be an integer between 1 and 100"},
    )


def task_not_found(task_id: str) -> ApiResponse:
    return ApiResponse(404, {"task_id": task_id, "status": "not_found"})


def serialize_task_event(item: TaskEvent) -> dict[str, object]:
    event = item.event
    payload = event.payload
    if (
        event.event_type is EventType.USER_MESSAGE_RECEIVED
        and payload.get("source") == "session_handoff"
    ):
        payload = {"content": payload.get("content", "")}
    return {
        "event_id": str(event.event_id),
        "sequence": item.task_sequence,
        "event_type": event.event_type.value,
        "actor": event.actor.value,
        "created_at": event.created_at.isoformat(),
        "payload": payload,
    }


def is_user_task_event(item: TaskEvent) -> bool:
    event = item.event
    if event.event_type in {
        EventType.SESSION_HANDOFF_COMMITTED,
        EventType.SESSION_HANDOFF_RECEIVED,
    }:
        return False
    if item.segment_id != TaskId(item.task_id) and event.event_type in {
        EventType.SESSION_CREATED,
        EventType.TASK_PREPARED,
    }:
        return False
    if event.event_type is EventType.USER_MESSAGE_RECEIVED:
        return event.payload.get("actor_kind") != HandoffActorKind.AUTOMATION.value
    return True
