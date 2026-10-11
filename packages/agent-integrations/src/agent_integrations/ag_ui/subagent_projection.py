"""Pure projection of subagent lifecycle and command-carried child results."""

from collections.abc import Mapping

from ag_ui.core import CustomEvent, Event
from agent_core.domain.events import EventType, SessionEvent

from agent_integrations.ag_ui.client_state_projection import project_client_state
from agent_integrations.ag_ui.payload_validation import (
    optional_payload_text as _optional_payload_text,
)
from agent_integrations.ag_ui.payload_validation import (
    required_payload_text as _required_payload_text,
)


def project_subagent_event(event: SessionEvent, *, timestamp: int) -> tuple[Event, ...]:
    payload = event.payload
    if event.event_type is EventType.SUBAGENT_DELEGATED:
        arguments = payload.get("arguments")
        details = arguments if isinstance(arguments, Mapping) else {}
        return (
            CustomEvent(
                timestamp=timestamp,
                name="zebra.subagent",
                value={
                    "child_task_id": _required_payload_text(payload, "child_task_id"),
                    "delegation_reason": _optional_payload_text(details, "delegation_reason"),
                    "objective": _optional_payload_text(details, "objective"),
                    "status": "running",
                    "tool_call_id": _required_payload_text(payload, "tool_call_id"),
                },
            ),
        )
    if event.event_type in {
        EventType.SUBAGENT_STARTED,
        EventType.SUBAGENT_COMPLETED,
        EventType.SUBAGENT_FAILED,
        EventType.SUBAGENT_CANCELLED,
    }:
        return (
            CustomEvent(
                timestamp=timestamp,
                name="zebra.subagent",
                value={
                    key: payload[key]
                    for key in (
                        "confidence",
                        "model_calls_used",
                        "source_count",
                        "status",
                        "subagent_id",
                        "tool_calls_used",
                    )
                    if key in payload
                },
            ),
        )
    if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
        return ()
    client_state = project_client_state(event, timestamp=timestamp)
    projected: list[Event] = list(client_state or ())
    command_payload = payload.get("payload")
    child_results = (
        command_payload.get("child_results") if isinstance(command_payload, Mapping) else None
    )
    if not isinstance(child_results, list):
        return tuple(projected)
    for result in child_results:
        if not isinstance(result, Mapping):
            continue
        child_task_id = _optional_payload_text(result, "child_task_id")
        status = _optional_payload_text(result, "status")
        if child_task_id is None or status is None:
            continue
        projected.append(
            CustomEvent(
                timestamp=timestamp,
                name="zebra.subagent",
                value={"child_task_id": child_task_id, "status": status},
            )
        )
    return tuple(projected)
