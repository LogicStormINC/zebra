from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.plans import SessionPlan
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.completion_blocking import current_task_plan
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)

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

REQUIRED_PLAN_GUIDANCE = (
    "Required Plan contract:\n"
    "- This Task has plan_required=true. Before finalizing or calling any "
    "substantive tool, first call agent.plan with a non-empty durable Plan.\n"
    "- agent.clarify may be called first only when user input is required.\n"
    "- Finishing or proposing substantive work without a durable Plan causes "
    "the Task to fail as required_plan_not_created."
)


def append_capability_guidance(
    messages: list[SessionMessage],
    tools: tuple[ModelToolDefinition, ...],
    *,
    created_at: datetime,
    plan_required: bool = False,
) -> None:
    names = {tool.name for tool in tools}
    guidance = "\n\n".join(
        text
        for name, text in (
            (
                "agent.plan",
                REQUIRED_PLAN_GUIDANCE if plan_required else "",
            ),
            ("agent.plan", PLAN_ACTIVATION_GUIDANCE),
            ("agent.research", MODEL_NATIVE_DELEGATION_GUIDANCE),
        )
        if name in names and text
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


def required_plan_action(
    context: HarnessContext,
    messages: Sequence[SessionMessage],
    completion: ModelCompletion,
    emitted_events: Sequence[HarnessEventDraft],
    *,
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: Mapping[str, object],
) -> Literal["continue", "nudge", "fail"]:
    calls = completion.tool_calls
    if (
        not context.task.plan_required
        or current_task_plan(context, emitted_events).steps
    ):
        return "continue"
    if calls and calls[0].name == "agent.clarify":
        return "continue"
    if calls and calls[0].name == "agent.plan" and _has_nonempty_plan(calls[0].arguments):
        return "continue"
    if metadata.get("required_plan_nudge_attempted") is True or any(
        message.metadata.get("required_plan_nudge") is True for message in messages
    ):
        return "fail"
    model_limit = context.task.max_model_calls
    if model_limit is not None and model_calls_used + 1 >= model_limit:
        return "fail"
    tool_limit = context.task.max_tool_calls
    if tool_limit is not None and tool_calls_executed >= tool_limit:
        return "fail"
    return "nudge"


def append_required_plan_nudge(
    messages: list[SessionMessage],
    completion: ModelCompletion,
    *,
    created_at: datetime,
) -> None:
    names = [call.name for call in completion.tool_calls]
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content=(
                "Runtime contract observation: plan_required=true, but no non-empty "
                "durable Plan exists. The prior response tried to finalize or proposed "
                f"substantive tools before planning: {names}. Re-evaluate once and call "
                "agent.plan first with non-empty steps. A valid Plan may be followed by "
                "necessary tools in the same response. If user input is needed first, "
                "call agent.clarify alone. Any other response fails the Task as "
                "required_plan_not_created."
            ),
            created_at=created_at,
            metadata={"required_plan_nudge": True},
        )
    )


def required_plan_failure(
    completion: ModelCompletion,
    emitted_events: list[HarnessEventDraft],
    *,
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: Mapping[str, object],
) -> HarnessAttemptResult:
    return build_attempt_result(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="required durable Plan was not created",
        assistant_message=completion.assistant_message.content,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={**metadata, "stop_reason": "required_plan_not_created"},
    )


def _has_nonempty_plan(arguments: Mapping[str, object]) -> bool:
    if "steps" not in arguments:
        return False
    try:
        return bool(SessionPlan.model_validate({"steps": arguments["steps"]}).steps)
    except ValueError:
        return False
