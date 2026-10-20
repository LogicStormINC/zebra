"""Explicit historical scheduler wire conversion; never selected by Host names."""
from agent_core.domain.host_authority import HostContextEnvelope


def legacy_resources(context: HostContextEnvelope) -> list[dict[str, str]]:
    return [
        {"type": ref.resource_type, "id": ref.resource_id}
        for ref in context.resource_refs if ref.resource_type.startswith("trench.")
    ]


def legacy_principal(context: HostContextEnvelope) -> dict[str, object]:
    return {
        "activeSourceIds": [
            ref.resource_id for ref in context.resource_refs
            if ref.resource_type == "trench.source"
        ],
        "agentScopes": list(context.scopes),
    }
