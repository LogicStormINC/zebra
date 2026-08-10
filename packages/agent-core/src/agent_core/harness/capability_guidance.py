from collections.abc import Mapping, Sequence
from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.harness.completion_blocking import current_task_plan
from agent_core.harness.models import HarnessContext, HarnessEventDraft

_PLAN_ACTIVATION_POLICY = "plan-activation.v1"

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

PLAN_ACTIVATION_GUIDANCE = (
    "Plan and evidence activation:\n"
    "- If a goal clearly requires durable coordination across dependent steps, "
    "evidence sources, or tool actions, you must first call agent.plan to establish "
    "a concise durable Plan before substantive work.\n"
    "- Keep the Plan concise and update its statuses as work progresses.\n"
    "- When conclusions depend on user-scoped or mutable facts and applicable "
    "authorized typed read tools are advertised, verify them with at least one "
    "relevant authoritative typed read before finalizing; do not rely on general "
    "knowledge or prompt summaries alone.\n"
    "- Simple one-step tasks may proceed without a Plan. Short linear sequences and "
    "multiple independent reads or checks do not require a Plan by themselves."
)


def append_capability_guidance(
    messages: list[SessionMessage],
    tools: tuple[ModelToolDefinition, ...],
    *,
    created_at: datetime,
) -> None:
    names = {tool.name for tool in tools}
    guidance = "\n\n".join(
        text
        for name, text in (
            ("agent.plan", PLAN_ACTIVATION_GUIDANCE),
            ("agent.research", MODEL_NATIVE_DELEGATION_GUIDANCE),
        )
        if name in names
    )
    if not guidance:
        return
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content=guidance,
            created_at=created_at,
            metadata=(
                {"plan_activation_policy": _PLAN_ACTIVATION_POLICY}
                if "agent.plan" in names
                else {}
            ),
        )
    )


def should_check_plan_activation(
    context: HarnessContext,
    messages: Sequence[SessionMessage],
    completion: ModelCompletion,
    emitted_events: Sequence[HarnessEventDraft],
    *,
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: Mapping[str, object],
) -> bool:
    calls = completion.tool_calls
    if (
        len(calls) < 2
        or metadata.get("plan_activation_check_attempted") is True
        or metadata.get("clarification_continuation") is True
        or tool_calls_executed != 0
        or calls[0].name in {"agent.clarify", "agent.plan"}
        or current_task_plan(context, emitted_events).steps
        or not any(
            message.metadata.get("plan_activation_policy") == _PLAN_ACTIVATION_POLICY
            for message in messages
        )
    ):
        return False
    model_limit = context.task.max_model_calls
    if model_limit is not None and model_calls_used + 1 >= model_limit:
        return False
    tool_limit = context.task.max_tool_calls
    return tool_limit is None or tool_calls_executed + len(calls) < tool_limit


def append_plan_activation_check(
    messages: list[SessionMessage],
    completion: ModelCompletion,
    *,
    created_at: datetime,
) -> None:
    names = ", ".join(call.name for call in completion.tool_calls)
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content=(
                "Runtime plan-activation check: the previous response proposed "
                f"these tools before any durable Plan: {names}. Re-evaluate once. "
                "If the goal requires durable coordination, call agent.plan first; "
                "necessary substantive tools may follow it in the same response. "
                "If this is only a simple one-step or short linear sequence, re-propose "
                "the necessary tools without a Plan. This check will not repeat."
            ),
            created_at=created_at,
            metadata={"plan_activation_check": True},
        )
    )
