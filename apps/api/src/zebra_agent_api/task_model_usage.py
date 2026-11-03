from collections.abc import Iterable
from typing import Any

from agent_core.application.task_model_usage import advance_model_usage, public_model_usage
from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEvent


def summarize_task_model_usage(events: Iterable[TaskEvent]) -> dict[str, object] | None:
    """Return the bounded public usage summary for a durable Task."""
    state: dict[str, Any] = {}
    for item in events:
        if item.event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            state = advance_model_usage(state, item.event.payload)
    return public_model_usage(state)
