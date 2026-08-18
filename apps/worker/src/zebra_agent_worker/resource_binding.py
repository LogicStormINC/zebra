"""Generic resource binding resolution for Host Tool invocations.

AL-WORKER-GENERIC-01: the Worker executes only the generic steps from the
plan — extract the argument value, build the HostResourceRef, exact-match it
against the Task's granted resource_refs. Host-specific vocabulary lives in
manifest declarations or the legacy Host adapter, never here.
"""

from __future__ import annotations

from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.host_capability_manifests import ResourceBindingRule
from agent_core.domain.tools import ToolCall

INVALID_RESOURCE_ID = "invalid"


def resolve_required_resource(
    bindings: tuple[ResourceBindingRule, ...],
    tool_call: ToolCall,
    context: HostContextEnvelope,
) -> HostResourceRef | None:
    """Resolve the primary required resource for one tool call.

    Semantics preserved from the legacy Worker mapping: a matched resource is
    returned as granted; an unmatched or malformed argument produces a typed
    ref that the invocation gate rejects (``resource_denied``); tools without
    required binding rules impose no resource requirement.
    """

    required_rules = tuple(rule for rule in bindings if rule.required)
    if not required_rules:
        return None
    primary = required_rules[0]
    value = tool_call.arguments.get(primary.argument_name)
    if not isinstance(value, str) or not value.strip():
        return HostResourceRef(type=primary.resource_type, id=INVALID_RESOURCE_ID)
    target = value.strip()
    for resource in context.resource_refs:
        if resource.resource_type == primary.resource_type and resource.resource_id == target:
            return resource
    return HostResourceRef(type=primary.resource_type, id=target)
