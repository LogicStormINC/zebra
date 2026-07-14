from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall


class ApprovedContinuationError(ValueError):
    """Raised when an approved call cannot be resumed safely."""


@dataclass(frozen=True)
class ApprovedContinuation:
    completion: ModelCompletion
    tool_call: ToolCall


def recover_approved_continuation(
    events: list[SessionEvent],
) -> ApprovedContinuation | None:
    requested: SessionEvent | None = None
    granted: SessionEvent | None = None
    execution_started = False
    for event in events:
        if event.event_type is EventType.APPROVAL_REQUESTED:
            requested = event
            granted = None
            execution_started = False
        elif requested is not None and event.event_type is EventType.APPROVAL_GRANTED:
            granted = event
        elif granted is not None and event.event_type is EventType.TOOL_EXECUTION_STARTED:
            execution_started = True
    if requested is None or granted is None:
        return None
    if execution_started:
        raise ApprovedContinuationError(
            "approved tool continuation has uncertain prior execution state"
        )
    tool_call_id = _required_string(requested.payload, "tool_call_id")
    fingerprint = _required_string(requested.payload, "call_fingerprint")
    if granted.payload.get("tool_call_id") != tool_call_id or (
        granted.payload.get("call_fingerprint") != fingerprint
    ):
        raise ApprovedContinuationError("approval grant does not match pending tool call")
    arguments = requested.payload.get("arguments")
    if not isinstance(arguments, dict):
        raise ApprovedContinuationError("pending tool call arguments are unavailable")
    tool_call = ToolCall(
        tool_call_id=ToolCallId(UUID(tool_call_id)),
        name=_required_string(requested.payload, "tool_name"),
        arguments=arguments,
        created_at=requested.created_at,
        provider_call_id=_optional_string(requested.payload.get("provider_call_id")),
    )
    if tool_call.approval_fingerprint != fingerprint:
        raise ApprovedContinuationError("pending tool call fingerprint is invalid")
    assistant_message = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.ASSISTANT,
        content=_required_string(requested.payload, "assistant_message"),
        created_at=requested.created_at,
        tool_calls=(tool_call,),
    )
    return ApprovedContinuation(
        completion=ModelCompletion(
            assistant_message=assistant_message,
            tool_calls=(tool_call,),
        ),
        tool_call=tool_call,
    )


def _required_string(payload: dict[str, object], key: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise ApprovedContinuationError(f"pending tool call {key} is unavailable")
    return value


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
