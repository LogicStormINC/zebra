"""Stable prompt directives and tool-result shaping for the model step."""

import json
from collections.abc import Sequence
from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.task_contracts import TaskAcceptanceContract, infer_task_contract

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


def task_acceptance_message(
    user_input: str,
    *,
    created_at: datetime,
    contract: TaskAcceptanceContract | None = None,
) -> SessionMessage | None:
    contract = contract or infer_task_contract(user_input)
    requirements: list[str] = []
    if contract.min_characters > 1:
        requirements.append("provide a substantive answer rather than a short acknowledgement")
    if contract.require_structure:
        requirements.append("organize the answer into clear sections or bullets")
    if contract.require_evidence_reference:
        requirements.append(
            "base factual claims on successful tool evidence, deduplicate repeated results, "
            "and reconcile material source conflicts"
        )
    if contract.require_matching_citation:
        requirements.append(
            "cite exact source URLs returned by the tools near supported claims; when using "
            "Markdown, put only the exact URL inside the link destination and keep annotations "
            "outside it"
        )
    if contract.require_verification:
        requirements.append(
            "verify the resulting state after any mutation or external operation "
            "before claiming completion"
        )
    if contract.require_artifact:
        requirements.append("produce and reference the requested durable artifact")
    if not requirements:
        return None
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.SYSTEM,
        content=(
            f"Task type: {contract.task_type.value}\n"
            f"Goal: {contract.goal}\n"
            "Required outcomes: " + ", ".join(contract.required_outcomes) + "\n"
            "Task acceptance requirements:\n- "
            + "\n- ".join(requirements)
            + "\nSeparate sourced facts from inference and uncertainty. Never invent a citation."
            " Use the minimum sufficient tool sequence, do not repeat a failed call with identical "
            "arguments, and stop collecting once every required outcome is supported."
        ),
        created_at=created_at,
    )


def final_answer_instruction(*, created_at: datetime) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=(
            "Answer the original request using the available tool results. Do not request "
            "another tool or mention internal budgets. Preserve every response constraint "
            "provided by the host or original request, including requested length, structure, "
            "language, and citation format. Prefer a concise synthesis over an exhaustive dump. "
            "Separate completed work from pending or blocked work. If evidence is insufficient, "
            "state what remains unknown without claiming quota exhaustion."
        ),
        created_at=created_at,
    )


def tool_result_content(tool_result: ToolResult) -> str:
    observation = _model_tool_observation(tool_result)
    if (
        tool_result.output
        and len(observation) == 2
        and tool_result.status is ToolCallStatus.EXECUTED
    ):
        return tool_result.output
    return json.dumps(observation, ensure_ascii=False, sort_keys=True)


_MODEL_OBSERVATION_KEYS = (
    "artifact_id",
    "artifact_uri",
    "coverage",
    "detail",
    "has_more",
    "next_cursor",
    "page",
    "page_count",
    "reason",
    "result_count",
    "source_count",
    "total_count",
    "truncated",
)


def _model_tool_observation(tool_result: ToolResult) -> dict[str, object]:
    observation: dict[str, object] = {"status": tool_result.status.value}
    if tool_result.output:
        observation["output"] = tool_result.output
    for key in _MODEL_OBSERVATION_KEYS:
        value = tool_result.metadata.get(key)
        if _safe_observation_value(value):
            observation[key] = value
    return observation


def _safe_observation_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and len(value) <= 2_048
    if isinstance(value, bool | int | float):
        return True
    if isinstance(value, list | tuple):
        return len(value) <= 20 and all(_safe_observation_value(item) for item in value)
    if isinstance(value, dict):
        return len(value) <= 20 and all(
            isinstance(key, str) and len(key) <= 64 and _safe_observation_value(item)
            for key, item in value.items()
        )
    return False
