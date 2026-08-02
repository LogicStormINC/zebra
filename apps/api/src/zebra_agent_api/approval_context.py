from __future__ import annotations

from agent_core.domain.context_capsule import ContextSourceEventRange
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


def source_approval_call_aliases(
    events: list[SessionEvent],
    source_event_range: ContextSourceEventRange | None,
    pending_ids: set[str],
) -> dict[str, str]:
    if source_event_range is None:
        return {}
    aliases: dict[str, str] = {}
    for pending_id in pending_ids:
        candidates = {
            value.strip()
            for event in events
            if event.event_type is EventType.APPROVAL_REQUESTED
            and source_event_range.start_sequence
            <= event.sequence
            <= source_event_range.end_sequence
            for key in ("tool_call_id", "provider_call_id")
            if event.payload.get(key) == pending_id
            for paired_key in ("tool_call_id", "provider_call_id")
            if paired_key != key
            for value in (event.payload.get(paired_key),)
            if isinstance(value, str) and value.strip()
        }
        if len(candidates) == 1:
            aliases[pending_id] = candidates.pop()
    if len(aliases) != len(set(aliases.values())):
        return {}
    return aliases


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
        "provider_tool_name",
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
    provider_arguments = payload.get("provider_arguments")
    if isinstance(provider_arguments, dict):
        context["provider_arguments"] = provider_arguments
    return context


def serialize_approval_context(context: ApprovalContext | None) -> dict[str, object] | None:
    if context is None:
        return None
    return context.to_mapping()
