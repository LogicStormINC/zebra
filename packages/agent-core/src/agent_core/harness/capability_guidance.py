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
    "Plan activation:\n"
    "- For clearly multi-step work whose progress must persist or evolve across "
    "dependent steps, evidence sources, or tool actions, call agent.plan before "
    "substantive execution.\n"
    "- Keep the Plan concise and update its statuses as work progresses.\n"
    "- Simple one-step tasks may proceed without a Plan; do not create one merely "
    "because several independent reads are available."
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
    if messages:
        messages[-1] = messages[-1].model_copy(
            update={"content": f"{messages[-1].content}\n\n{guidance}"}
        )
        return
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content=guidance,
            created_at=created_at,
        )
    )
