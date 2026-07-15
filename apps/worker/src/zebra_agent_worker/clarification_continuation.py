from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.messages import SessionMessage
from agent_core.domain.tools import ToolCall


class ClarificationContinuationError(ValueError):
    """Raised when a clarification continuation cannot be resumed safely."""


@dataclass(frozen=True)
class ClarificationContinuation:
    tool_call: ToolCall
    response: str
    conversation: tuple[SessionMessage, ...]
    model_calls_used: int
    tool_calls_executed: int
    assistant_message: str


def recover_clarification_continuation(
    events: list[SessionEvent],
) -> ClarificationContinuation | None:
    requested: SessionEvent | None = None
    responded: SessionEvent | None = None
    continuation_started = False
    for event in events:
        if event.event_type is EventType.CLARIFICATION_REQUESTED:
            requested = event
            responded = None
            continuation_started = False
        elif requested is not None and event.event_type is EventType.CLARIFICATION_RESPONDED:
            responded = event
        elif (
            responded is not None
            and event.event_type is EventType.HARNESS_ATTEMPT_STARTED
            and event.payload.get("clarification_continuation") is True
        ):
            continuation_started = True
    if requested is None or responded is None:
        return None
    if continuation_started:
        raise ClarificationContinuationError(
            "clarification continuation has uncertain prior model-call state"
        )
    clarification_id = _required_string(requested.payload, "clarification_id")
    if responded.payload.get("clarification_id") != clarification_id:
        raise ClarificationContinuationError(
            "clarification response does not match pending request"
        )
    tool_call_id = _required_string(requested.payload, "tool_call_id")
    if tool_call_id != clarification_id:
        raise ClarificationContinuationError("clarification tool-call identity is invalid")
    return ClarificationContinuation(
        tool_call=ToolCall(
            tool_call_id=ToolCallId(UUID(tool_call_id)),
            name="agent.clarify",
            arguments={
                "question": _required_string(requested.payload, "question"),
                "choices": _choices(requested.payload.get("choices")),
                **_optional_context(requested.payload.get("context")),
            },
            created_at=requested.created_at,
            provider_call_id=_optional_string(requested.payload.get("provider_call_id")),
        ),
        response=_required_string(responded.payload, "content"),
        conversation=_conversation(requested.payload.get("conversation")),
        model_calls_used=_non_negative_int(requested.payload.get("model_calls_used"), 1),
        tool_calls_executed=_non_negative_int(requested.payload.get("tool_calls_executed"), 0),
        assistant_message=_required_string(requested.payload, "assistant_message"),
    )


def _required_string(payload: dict[str, object], key: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise ClarificationContinuationError(f"clarification {key} is unavailable")
    return value


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _choices(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ClarificationContinuationError("clarification choices are invalid")
    return value


def _optional_context(value: object) -> dict[str, str]:
    context = _optional_string(value)
    return {"context": context} if context is not None else {}


def _conversation(value: object) -> tuple[SessionMessage, ...]:
    if not isinstance(value, list):
        raise ClarificationContinuationError("clarification conversation is invalid")
    try:
        return tuple(SessionMessage.model_validate(item) for item in value)
    except ValueError as exc:
        raise ClarificationContinuationError("clarification conversation is invalid") from exc


def _non_negative_int(value: object, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ClarificationContinuationError("clarification counters are invalid")
    return value
