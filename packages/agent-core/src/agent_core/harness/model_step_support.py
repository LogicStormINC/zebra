"""Stable prompt directives and tool-result shaping for the model step."""

import json
from collections.abc import Sequence
from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelToolDefinition
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


def selected_skill_message(
    skill_components: tuple[str, ...],
    available_tools: Sequence[ModelToolDefinition],
    *,
    created_at: datetime,
) -> SessionMessage | None:
    names = {tool.name for tool in available_tools}
    if not skill_components or not {"skills.list", "skills.read"}.issubset(names):
        return None
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.SYSTEM,
        content=(
            "Selected Skills are frozen for this task. The selected identifiers are: "
            f"{', '.join(skill_components)}. Before producing a substantial deliverable, "
            "call skills.list to resolve each selected Skill name or published skill_id, then call "
            "skills.read for every applicable selected Skill and follow its workflow within "
            "the existing tool and authority boundaries. Never claim that a Skill was used "
            "unless it was read."
        ),
        created_at=created_at,
    )


def final_answer_instruction(*, created_at: datetime) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=(
            "Answer the original request using the available tool results. Do not request "
            "another tool or mention internal budgets. If evidence is insufficient, state "
            "what remains unknown without claiming quota exhaustion."
        ),
        created_at=created_at,
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
