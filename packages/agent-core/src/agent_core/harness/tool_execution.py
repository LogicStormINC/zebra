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
