from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.domain.events import SessionEvent


@dataclass
class _PendingAttemptTrace:
    attempt_number: int
    assistant_message: str | None = None
    tools: list[dict[str, object]] = field(default_factory=list)
    pending_tool_name: str | None = None
    pending_tool_arguments: dict[str, object] = field(default_factory=dict)
    pending_policy_decision: str | None = None


def serialize_trace_events(events: tuple[SessionEvent, ...]) -> list[dict[str, object]]:
    attempts: dict[int, _PendingAttemptTrace] = {}
    for event in events:
        raw_attempt_number = event.payload.get("attempt_number")
        if not isinstance(raw_attempt_number, int) or raw_attempt_number <= 0:
            continue
        attempt = attempts.setdefault(
            raw_attempt_number,
            _PendingAttemptTrace(attempt_number=raw_attempt_number),
        )
        if event.event_type.value == "model_response_received":
            assistant_message = event.payload.get("assistant_message")
            if isinstance(assistant_message, str):
                attempt.assistant_message = assistant_message
        elif event.event_type.value == "tool_call_proposed":
            tool_name = event.payload.get("tool_name")
            arguments = event.payload.get("arguments")
            if isinstance(tool_name, str):
                attempt.pending_tool_name = tool_name
            if isinstance(arguments, dict):
                attempt.pending_tool_arguments = {
                    str(key): value for key, value in arguments.items()
                }
        elif event.event_type.value == "policy_decision_made":
            decision = event.payload.get("decision")
            if isinstance(decision, str):
                attempt.pending_policy_decision = decision
        elif event.event_type.value in {"tool_execution_completed", "tool_execution_failed"}:
            tool_name = event.payload.get("tool_name")
            status = event.payload.get("status")
            if not isinstance(tool_name, str) or not isinstance(status, str):
                continue
            output = event.payload.get("output")
            metadata = event.payload.get("metadata")
            attempt.tools.append(
                {
                    "tool_name": tool_name,
                    "status": status,
                    "arguments": (
                        dict(attempt.pending_tool_arguments)
                        if tool_name == attempt.pending_tool_name
                        else {}
                    ),
                    "output": output if isinstance(output, str) else "",
                    "metadata": dict(metadata) if isinstance(metadata, dict) else {},
                    "policy_decision": attempt.pending_policy_decision,
                }
            )
            attempt.pending_tool_name = None
            attempt.pending_tool_arguments = {}
            attempt.pending_policy_decision = None
    return [
        {
            "attempt_number": attempt.attempt_number,
            "assistant_message": attempt.assistant_message,
            "tools": attempt.tools,
        }
        for _, attempt in sorted(attempts.items(), key=lambda item: item[0])
    ]
