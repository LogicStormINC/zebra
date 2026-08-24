"""Recover a waiting-children parent continuation from durable events.

Mirrors the clarification/approval continuation rails. Trust rules:

- only SESSION_COMMAND_ACCEPTED events written by the HARNESS actor can
  wake a waiting parent — public USER resume commands are ignored, so a
  user cannot forge child results;
- the wakeup must pair with the CURRENT delegation epoch (every
  SUBAGENT_DELEGATED event since the last resume/terminal boundary that
  precedes a delegation) and carry exactly that epoch's children;
- an optional verifier re-derives each child result from durable state
  (terminal delegation link plus the child's own terminal event) before
  the results are injected into the parent conversation.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall


class ChildWakeupContinuationError(ValueError):
    """Raised when a waiting-children continuation cannot be resumed safely."""


ChildResultVerifier = Callable[[str, str, str], None]


@dataclass(frozen=True)
class ChildResultDelivery:
    child_task_id: str
    status: str
    summary: str


@dataclass(frozen=True)
class ChildWakeupContinuation:
    """tool_calls[i] and child_results[i] belong to the same delegation."""

    tool_calls: tuple[ToolCall, ...]
    child_results: tuple[ChildResultDelivery, ...]
    conversation: tuple[SessionMessage, ...]
    model_calls_used: int
    tool_calls_executed: int
    assistant_message: str

    @property
    def tool_call(self) -> ToolCall:
        return self.tool_calls[-1]


def recover_child_wakeup_continuation(
    events: list[SessionEvent],
    *,
    verifier: ChildResultVerifier | None = None,
) -> ChildWakeupContinuation | None:
    delegated_indexes = [
        index
        for index, event in enumerate(events)
        if event.event_type is EventType.SUBAGENT_DELEGATED
    ]
    if not delegated_indexes:
        return None
    # The epoch: delegations after the last resume/terminal boundary that
    # still has a delegation after it. The SESSION_RESUMED appended by the
    # restore step of THIS resume has no delegation after it, so it never
    # cuts the epoch being recovered.
    cut = -1
    for index, event in enumerate(events):
        if event.event_type is EventType.SUBAGENT_DELEGATED:
            continue
        if event.event_type in (
            EventType.SESSION_RESUMED,
            EventType.SESSION_COMPLETED,
            EventType.SESSION_FAILED,
            EventType.SESSION_CANCELLED,
        ) and any(delegated > index for delegated in delegated_indexes):
            cut = index
    epoch = [events[index] for index in delegated_indexes if index > cut]
    if not epoch:
        return None
    last_delegated_index = delegated_indexes[-1]
    wakeup: SessionEvent | None = None
    continuation_started = False
    for event in events[last_delegated_index + 1 :]:
        if _is_child_wakeup_command(event):
            wakeup = event
        elif (
            wakeup is not None
            and event.event_type is EventType.HARNESS_ATTEMPT_STARTED
            and event.payload.get("child_wakeup_continuation") is True
        ):
            continuation_started = True
    if wakeup is None:
        return None
    if continuation_started:
        raise ChildWakeupContinuationError(
            "child wakeup continuation has uncertain prior model-call state"
        )
    child_results = _child_results(wakeup.payload.get("payload"))
    epoch_children = {_required_string(event.payload, "child_task_id") for event in epoch}
    delivered_children = {result.child_task_id for result in child_results}
    if delivered_children != epoch_children:
        raise ChildWakeupContinuationError(
            "child wakeup command does not cover exactly the delegated children"
        )
    if verifier is not None:
        for result in child_results:
            verifier(result.child_task_id, result.status, result.summary)
    tool_calls = tuple(_tool_call_of(event) for event in epoch)
    results_by_child = {result.child_task_id: result for result in child_results}
    aligned_results = tuple(
        results_by_child[_required_string(event.payload, "child_task_id")] for event in epoch
    )
    conversation = _conversation_without_stubs(
        epoch[-1].payload.get("conversation"),
        {str(call.tool_call_id) for call in tool_calls},
    )
    return ChildWakeupContinuation(
        tool_calls=tool_calls,
        child_results=aligned_results,
        conversation=conversation,
        model_calls_used=_non_negative_int(epoch[-1].payload.get("model_calls_used"), 1),
        tool_calls_executed=_non_negative_int(epoch[-1].payload.get("tool_calls_executed"), 0),
        assistant_message=_required_string(epoch[-1].payload, "assistant_message"),
    )


def _is_child_wakeup_command(event: SessionEvent) -> bool:
    """Only harness-actor resume commands carrying child results qualify."""

    return (
        event.actor is EventActor.HARNESS
        and event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        and event.payload.get("kind") == "resume"
        and isinstance(event.payload.get("payload"), dict)
        and isinstance(event.payload["payload"].get("child_results"), list)
    )


def _tool_call_of(event: SessionEvent) -> ToolCall:
    tool_call_id = _required_string(event.payload, "tool_call_id")
    try:
        return ToolCall(
            tool_call_id=ToolCallId(UUID(tool_call_id)),
            name=_required_string(event.payload, "tool_name"),
            arguments=_arguments(event.payload.get("arguments")),
            created_at=event.created_at,
            provider_call_id=_optional_string(event.payload.get("provider_call_id")),
        )
    except ValueError as exc:
        raise ChildWakeupContinuationError("delegated tool call is invalid") from exc


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


def _conversation_without_stubs(
    value: object, tool_call_ids: set[str]
) -> tuple[SessionMessage, ...]:
    """Drop the 'materialized' stub results; the real ones are injected."""

    if not isinstance(value, list):
        raise ChildWakeupContinuationError("delegated conversation is invalid")
    try:
        messages = tuple(SessionMessage.model_validate(item) for item in value)
    except ValueError as exc:
        raise ChildWakeupContinuationError("delegated conversation is invalid") from exc
    return tuple(
        message
        for message in messages
        if not (message.role is MessageRole.TOOL and message.tool_call_id in tool_call_ids)
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
