"""Stable prompt directives and tool-result shaping for the model step."""

import json

from agent_core.domain.tools import ToolCallStatus, ToolResult

MODEL_NATIVE_DELEGATION_GUIDANCE = (
    "Subagent delegation:\n"
    "- Answer directly when context is sufficient or evidence collection is not needed.\n"
    "- Use a normal parent tool for one direct operation or a short linear sequence.\n"
    "- Call agent.research only for bounded, independent, multi-step evidence "
    "collection whose separate context is materially useful.\n"
    "- Words such as research, search, analysis, or comparison do not require "
    "delegation by themselves.\n"
    "- Every agent.research call must include objective and a concise "
    "delegation_reason explaining why direct work is less suitable."
)

MODEL_REQUIRED_DELEGATION_DIRECTIVE = (
    "Subagent delegation (MANDATORY for this task):\n"
    "- You MUST call agent.research exactly once before producing your final "
    "answer.\n"
    "- Answering without delegating is a task failure with reason "
    "delegation_required_not_used.\n"
    "- The call must include a specific objective and a concise "
    "delegation_reason."
)

ZEBRA_AGENT_IDENTITY_DIRECTIVE = (
    "You are Zebra Agent, a provider-neutral engineering agent runtime. "
    "When asked who you are, identify yourself as Zebra Agent. Do not claim to be "
    "Claude, ChatGPT, DeepSeek, or the underlying model provider. Describe capabilities "
    "only from the tools and runtime evidence actually available in this session."
)


def tool_result_content(tool_result: ToolResult) -> str:
    if tool_result.output:
        return tool_result.output
    if tool_result.status is ToolCallStatus.EXECUTED:
        return "Tool executed."
    observation: dict[str, object] = {"status": tool_result.status.value}
    for key in ("reason", "detail"):
        value = tool_result.metadata.get(key)
        if isinstance(value, str | int | float | bool):
            observation[key] = value
    return json.dumps(observation, ensure_ascii=False, sort_keys=True)
