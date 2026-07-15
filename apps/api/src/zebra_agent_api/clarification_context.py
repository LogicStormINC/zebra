from agent_core.domain.clarifications import ClarificationContext


def serialize_clarification_context(
    context: ClarificationContext | None,
) -> dict[str, object] | None:
    if context is None:
        return None
    body: dict[str, object] = {
        "clarification_id": context.clarification_id,
        "question": context.question,
        "choices": list(context.choices),
        "requested_at": context.requested_at.isoformat(),
    }
    if context.context is not None:
        body["context"] = context.context
    return body
