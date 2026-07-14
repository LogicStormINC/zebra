from dataclasses import dataclass

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.models import HarnessContext, HarnessEventDraft
from agent_core.ports.tool_gateway import ToolGatewayPort


@dataclass(frozen=True)
class ToolExecutionStep:
    result: ToolResult
    metadata: dict[str, object]


def execute_tool_call(
    context: HarnessContext,
    tool_call: ToolCall,
    *,
    tool_gateway: ToolGatewayPort,
    verifier: VerifierHook,
    emitted_events: list[HarnessEventDraft],
    emit_execution_started: bool = True,
) -> ToolExecutionStep:
    if emit_execution_started:
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_STARTED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": context.attempt.number,
                    "tool_name": tool_call.name,
                    "tool_call_id": str(tool_call.tool_call_id),
                },
            )
        )
    tool_result = tool_gateway.execute(tool_call)
    return record_tool_result(
        context,
        tool_call,
        tool_result,
        verifier=verifier,
        emitted_events=emitted_events,
    )


def record_tool_result(
    context: HarnessContext,
    tool_call: ToolCall,
    tool_result: ToolResult,
    *,
    verifier: VerifierHook,
    emitted_events: list[HarnessEventDraft],
) -> ToolExecutionStep:
    emitted_events.extend(
        _subagent_lifecycle_events(
            context,
            tool_call=tool_call,
            tool_result=tool_result,
        )
    )
    emitted_events.append(
        HarnessEventDraft(
            event_type=(
                EventType.TOOL_EXECUTION_COMPLETED
                if tool_result.status is ToolCallStatus.EXECUTED
                else EventType.TOOL_EXECUTION_FAILED
            ),
            actor=EventActor.TOOL,
            payload={
                "attempt_number": context.attempt.number,
                "tool_name": tool_call.name,
                "status": tool_result.status.value,
                "output": tool_result.output,
                "metadata": tool_result.metadata,
            },
        )
    )
    verification = verifier.verify(
        context,
        tool_result.status.value,
        tool_result.output,
    )
    emitted_events.append(
        HarnessEventDraft(
            event_type=EventType.TESTS_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": context.attempt.number,
                "summary": verification.summary,
                "passed": verification.passed,
                "metadata": verification.metadata,
            },
        )
    )
    return ToolExecutionStep(
        result=tool_result,
        metadata={
            "tool_name": tool_call.name,
            "tool_status": tool_result.status.value,
            "tool_output": tool_result.output,
            "tool_metadata": tool_result.metadata,
            "verification_summary": verification.summary,
            "verification_passed": verification.passed,
            "verification_metadata": verification.metadata,
        },
    )


def _subagent_lifecycle_events(
    context: HarnessContext,
    *,
    tool_call: ToolCall,
    tool_result: ToolResult,
) -> tuple[HarnessEventDraft, ...]:
    if tool_call.name != "agent.research":
        return ()
    metadata = tool_result.metadata
    subagent_id = metadata.get("subagent_id")
    status = metadata.get("subagent_status")
    provenance = metadata.get("provenance")
    if not isinstance(subagent_id, str) or not subagent_id:
        return ()
    if not isinstance(status, str) or not status:
        return ()
    if not isinstance(provenance, str) or not provenance:
        return ()
    limits = {
        "max_model_calls": _metadata_int(metadata, "max_model_calls", minimum=1),
        "max_tool_calls": _metadata_int(metadata, "max_tool_calls", minimum=1),
        "max_depth": _metadata_int(metadata, "max_depth", minimum=1),
    }
    base: dict[str, object] = {
        "attempt_number": context.attempt.number,
        "subagent_id": subagent_id,
        "status": "running",
        **limits,
        "model_calls_used": 0,
        "tool_calls_used": 0,
        "source_count": 0,
        "confidence": 0.0,
        "provenance": provenance,
    }
    terminal = {
        **base,
        "status": status,
        "model_calls_used": _metadata_int(metadata, "model_calls_used"),
        "tool_calls_used": _metadata_int(metadata, "tool_calls_used"),
        "source_count": _metadata_int(metadata, "source_count"),
        "confidence": _metadata_float(metadata, "confidence"),
    }
    terminal_type = {
        "completed": EventType.SUBAGENT_COMPLETED,
        "cancelled": EventType.SUBAGENT_CANCELLED,
    }.get(status, EventType.SUBAGENT_FAILED)
    return (
        HarnessEventDraft(
            event_type=EventType.SUBAGENT_STARTED,
            actor=EventActor.HARNESS,
            payload=base,
        ),
        HarnessEventDraft(
            event_type=terminal_type,
            actor=EventActor.HARNESS,
            payload=terminal,
        ),
    )


def _metadata_int(
    metadata: dict[str, object],
    key: str,
    *,
    minimum: int = 0,
) -> int:
    value = metadata.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= minimum:
        return value
    return minimum


def _metadata_float(metadata: dict[str, object], key: str) -> float:
    value = metadata.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return min(1.0, max(0.0, float(value)))
    return 0.0
