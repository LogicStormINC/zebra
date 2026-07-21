import json

from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)


def clarification_stop_result(
    context: HarnessContext,
    *,
    messages: list[SessionMessage],
    completion: ModelCompletion,
    tool_call: ToolCall,
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
) -> HarnessAttemptResult:
    request = ClarificationContext.from_tool_call(
        tool_call,
        assistant_message=completion.assistant_message.content,
        requested_at=context.attempt.started_at,
    )
    request_payload = request.to_mapping()
    request_payload.pop("requested_at", None)
    emitted_events.append(
        HarnessEventDraft(
            event_type=EventType.CLARIFICATION_REQUESTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": context.attempt.number,
                **request_payload,
                "conversation": [message.model_dump(mode="json") for message in messages],
                "model_calls_used": model_calls_used,
                "tool_calls_executed": tool_calls_executed,
            },
        )
    )
    return build_attempt_result(
        outcome=HarnessAttemptOutcome.WAITING_INPUT,
        summary="agent requested user clarification",
        assistant_message=completion.assistant_message.content,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={
            **metadata,
            "tool_name": tool_call.name,
            "clarification_id": request.clarification_id,
            "question": request.question,
        },
    )


def elicitation_stop_result(
    context: HarnessContext,
    *,
    messages: list[SessionMessage],
    completion: ModelCompletion,
    tool_call: ToolCall,
    message: str,
    requested_schema: dict[str, object] | None,
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
) -> HarnessAttemptResult:
    """Suspend a Task for an MCP elicitation, mapping it onto a ClarificationContext.

    The elicitation arrives as a synthesized payload (Phase A has no
    server-initiated JSON-RPC path); this mirrors ``clarification_stop_result``
    but tags the context with ``response_schema`` + ``elicitation_source``.
    """
    request = ClarificationContext.from_elicitation(
        message=message,
        requested_schema=requested_schema,
        tool_call_id=str(tool_call.tool_call_id),
        assistant_message=completion.assistant_message.content,
        requested_at=context.attempt.started_at,
    )
    request_payload = request.to_mapping()
    request_payload.pop("requested_at", None)
    emitted_events.append(
        HarnessEventDraft(
            event_type=EventType.CLARIFICATION_REQUESTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": context.attempt.number,
                **request_payload,
                "conversation": [message.model_dump(mode="json") for message in messages],
                "model_calls_used": model_calls_used,
                "tool_calls_executed": tool_calls_executed,
            },
        )
    )
    return build_attempt_result(
        outcome=HarnessAttemptOutcome.WAITING_INPUT,
        summary="agent requested user input via MCP elicitation",
        assistant_message=completion.assistant_message.content,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={
            **metadata,
            "tool_name": tool_call.name,
            "clarification_id": request.clarification_id,
            "question": request.question,
            "elicitation_source": request.effective_source,
        },
    )


def clarification_tool_result(
    tool_call_id: ToolCallId,
    clarification_id: str,
    response: str,
) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output=json.dumps(
            {
                "clarification_id": clarification_id,
                "user_response": response,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        metadata={"clarification_response": True},
    )
