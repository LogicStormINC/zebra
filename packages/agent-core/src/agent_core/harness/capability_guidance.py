from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelToolDefinition

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
        )
    )
