from __future__ import annotations

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.sessions import ApprovalContext


def latest_approval_context(events: list[SessionEvent]) -> dict[str, object] | None:
    for event in reversed(events):
        if event.event_type is not EventType.APPROVAL_REQUESTED:
            continue
        context = _approval_context_payload(event)
        if context:
            return context
    return None


def _approval_context_payload(event: SessionEvent) -> dict[str, object]:
    payload = event.payload
    context: dict[str, object] = {}
    for field in (
        "tool_name",
        "reason",
        "policy_profile",
        "route",
        "target",
        "network_profile",
        "tool_call_id",
        "provider_call_id",
        "assistant_message",
        "call_fingerprint",
    ):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            context[field] = value
    scope = payload.get("scope")
    if isinstance(scope, list | tuple):
        normalized = [item for item in scope if isinstance(item, str) and item.strip()]
        if normalized:
            context["scope"] = normalized
    arguments = payload.get("arguments")
    if isinstance(arguments, dict):
        context["arguments"] = arguments
    return context


def serialize_approval_context(context: ApprovalContext | None) -> dict[str, object] | None:
    if context is None:
        return None
    return context.to_mapping()
