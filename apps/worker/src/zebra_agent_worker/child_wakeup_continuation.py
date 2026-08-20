"""Recover a waiting-children parent continuation from durable events.

Mirrors the clarification/approval continuation rails: the
``SUBAGENT_DELEGATED`` event froze the exact join state (conversation,
counters, tool-call identity) at suspension time; the child wakeup's
``SESSION_COMMAND_ACCEPTED`` command carries the terminal child results.
Recovery pairs the two so the resumed parent injects the real child
result at the exact point the delegation happened.
"""

from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall


class ChildWakeupContinuationError(ValueError):
    """Raised when a waiting-children continuation cannot be resumed safely."""


@dataclass(frozen=True)
class ChildResultDelivery:
    child_task_id: str
    status: str
    summary: str


@dataclass(frozen=True)
class ChildWakeupContinuation:
    tool_call: ToolCall
    child_results: tuple[ChildResultDelivery, ...]
    conversation: tuple[SessionMessage, ...]
    model_calls_used: int
    tool_calls_executed: int
    assistant_message: str
    provider_call_id: str | None


def recover_child_wakeup_continuation(
    events: list[SessionEvent],
) -> ChildWakeupContinuation | None:
    delegated: SessionEvent | None = None
    wakeup: SessionEvent | None = None
    continuation_started = False
    for event in events:
        if event.event_type is EventType.SUBAGENT_DELEGATED:
            delegated = event
            wakeup = None
            continuation_started = False
        elif (
            delegated is not None
            and event.event_type is EventType.SESSION_COMMAND_ACCEPTED
            and _is_child_wakeup_command(event)
        ):
            wakeup = event
        elif (
            wakeup is not None
            and event.event_type is EventType.HARNESS_ATTEMPT_STARTED
            and event.payload.get("child_wakeup_continuation") is True
        ):
            continuation_started = True
    if delegated is None or wakeup is None:
        return None
    if continuation_started:
        raise ChildWakeupContinuationError(
            "child wakeup continuation has uncertain prior model-call state"
        )
    child_results = _child_results(wakeup.payload.get("payload"))
    delegated_child = _required_string(delegated.payload, "child_task_id")
    if all(result.child_task_id != delegated_child for result in child_results):
        raise ChildWakeupContinuationError(
            "child wakeup command does not carry the delegated child result"
        )
    tool_call_id = _required_string(delegated.payload, "tool_call_id")
    try:
        tool_call = ToolCall(
            tool_call_id=ToolCallId(UUID(tool_call_id)),
            name=_required_string(delegated.payload, "tool_name"),
            arguments=_arguments(delegated.payload.get("arguments")),
            created_at=delegated.created_at,
            provider_call_id=_optional_string(delegated.payload.get("provider_call_id")),
        )
    except ValueError as exc:
        raise ChildWakeupContinuationError("delegated tool call is invalid") from exc
    conversation = _conversation_without_stub(
        delegated.payload.get("conversation"), tool_call_id
    )
    return ChildWakeupContinuation(
        tool_call=tool_call,
        child_results=child_results,
        conversation=conversation,
        model_calls_used=_non_negative_int(delegated.payload.get("model_calls_used"), 1),
        tool_calls_executed=_non_negative_int(delegated.payload.get("tool_calls_executed"), 0),
        assistant_message=_required_string(delegated.payload, "assistant_message"),
        provider_call_id=_optional_string(delegated.payload.get("provider_call_id")),
    )


def _is_child_wakeup_command(event: SessionEvent) -> bool:
    payload = event.payload
    return (
        payload.get("kind") == "resume"
        and isinstance(payload.get("payload"), dict)
        and isinstance(payload["payload"].get("child_results"), list)
    )


def _child_results(value: object) -> tuple[ChildResultDelivery, ...]:
    if not isinstance(value, dict):
        raise ChildWakeupContinuationError("child wakeup payload is invalid")
    raw = value.get("child_results")
    if not isinstance(raw, list) or not raw:
        raise ChildWakeupContinuationError("child wakeup results are unavailable")
    results: list[ChildResultDelivery] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ChildWakeupContinuationError("child wakeup result is invalid")
        child_task_id = item.get("child_task_id")
        status = item.get("status")
        summary = item.get("summary")
        fields = [child_task_id, status, summary]
        if not all(isinstance(field, str) and field.strip() for field in fields):
            raise ChildWakeupContinuationError("child wakeup result fields are invalid")
        assert isinstance(child_task_id, str) and isinstance(status, str)
        assert isinstance(summary, str)
        results.append(
            ChildResultDelivery(
                child_task_id=child_task_id.strip(),
                status=status.strip(),
                summary=summary.strip(),
            )
        )
    return tuple(results)


def _conversation_without_stub(
    value: object, tool_call_id: str
) -> tuple[SessionMessage, ...]:
    """Drop the stub 'materialized' tool result; the real one is injected."""

    if not isinstance(value, list):
        raise ChildWakeupContinuationError("delegated conversation is invalid")
    try:
        messages = tuple(SessionMessage.model_validate(item) for item in value)
    except ValueError as exc:
        raise ChildWakeupContinuationError("delegated conversation is invalid") from exc
    return tuple(
        message
        for message in messages
        if not (
            message.role is MessageRole.TOOL and message.tool_call_id == tool_call_id
        )
    )


def _arguments(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ChildWakeupContinuationError("delegated arguments are unavailable")
    return dict(value)


def _required_string(payload: dict[str, object], key: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise ChildWakeupContinuationError(f"delegated {key} is unavailable")
    return value


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _non_negative_int(value: object, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ChildWakeupContinuationError("delegated counters are invalid")
    return value
