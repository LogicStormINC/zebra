from __future__ import annotations

from agent_core.domain.events import SessionEvent
from agent_core.harness.projection import HarnessTraceProjector


def serialize_trace_events(events: tuple[SessionEvent, ...]) -> list[dict[str, object]]:
    return [
        {
            "attempt_number": attempt.attempt_number,
            "assistant_message": attempt.assistant_message,
            "tools": [
                {
                    "tool_name": tool.tool_name,
                    "status": tool.status,
                    "arguments": tool.arguments,
                    "output": tool.output,
                    "metadata": tool.metadata,
                    "policy_decision": tool.policy_decision,
                    "policy_route": tool.policy_route,
                    "policy_target": tool.policy_target,
                    "policy_network_profile": tool.policy_network_profile,
                    "policy_scope": list(tool.policy_scope),
                }
                for tool in attempt.tools
            ],
        }
        for attempt in HarnessTraceProjector().project_events(events)
    ]
