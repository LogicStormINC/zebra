"""Grant-aware Host tool visibility for Worker model requests."""

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.modeling import ModelToolDefinition
from agent_integrations.host_tools import HostToolManifest
from agent_tools.contracts import ToolContract


def available_host_tools(
    manifest: HostToolManifest | None,
    context: HostContextEnvelope | None,
) -> tuple[ToolContract, ...]:
    if manifest is None or context is None:
        return ()
    granted_scopes = frozenset(context.scopes)
    granted_resource_types = frozenset(ref.resource_type for ref in context.resource_refs)
    return tuple(
        tool
        for tool in manifest.tools
        if frozenset(tool.scopes) <= granted_scopes
        and {
            rule.resource_type
            for rule in manifest.resource_bindings_for(tool.name)
            if rule.required
        }
        <= granted_resource_types
    )


def host_model_tools(
    manifest: HostToolManifest | None,
    context: HostContextEnvelope | None,
) -> tuple[ModelToolDefinition, ...]:
    if manifest is None:
        return ()
    return tuple(
        ModelToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters={
                "type": "object",
                "properties": {key: dict(value) for key, value in tool.argument_properties.items()},
                "required": list(tool.required_arguments),
                "additionalProperties": False,
            },
        )
        for tool in available_host_tools(manifest, context)
    )
