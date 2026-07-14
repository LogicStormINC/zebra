import json

from agent_core.domain.tools import ToolCall
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessEventDraft,
)


def build_attempt_result(
    *,
    outcome: HarnessAttemptOutcome,
    summary: str,
    assistant_message: str,
    model_calls_used: int,
    tool_calls_executed: int,
    emitted_events: list[HarnessEventDraft],
    metadata: dict[str, object],
) -> HarnessAttemptResult:
    return HarnessAttemptResult(
        outcome=outcome,
        summary=summary,
        metadata={
            "assistant_message": assistant_message,
            "model_calls_used": model_calls_used,
            "tool_calls_executed": tool_calls_executed,
            **metadata,
        },
        emitted_events=tuple(emitted_events),
    )


def action_fingerprint(tool_call: ToolCall) -> str:
    return json.dumps(
        {"name": tool_call.name, "arguments": tool_call.arguments},
        separators=(",", ":"),
        sort_keys=True,
    )
