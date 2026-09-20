"""Small replay helpers shared by the sequential tool loop."""

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.harness.attempt_result import action_fingerprint


def executed_action_fingerprints(messages: list[SessionMessage]) -> set[str]:
    completed_ids = {
        message.tool_call_id for message in messages if message.role is MessageRole.TOOL
    }
    return {
        action_fingerprint(call)
        for message in messages
        for call in message.tool_calls
        if (call.provider_call_id or str(call.tool_call_id)) in completed_ids
    }
