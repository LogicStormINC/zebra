from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_core.domain.mcp import normalize_mcp_allowlist

from agent_runtime.mcp_protocol import McpServerSpec
from agent_runtime.mcp_resources import McpResource, discover_mcp_resources
from agent_runtime.mcp_stdio import LocalStdioMcpTransport


@dataclass(frozen=True)
class McpToolCapability:
    name: str
    description: str
    input_fields: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "input_fields": list(self.input_fields),
        }


@dataclass(frozen=True)
class McpServerCapability:
    name: str
    tools: tuple[McpToolCapability, ...]
    resources: tuple[McpResource, ...] = ()

    def to_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tool_count": len(self.tools),
            "tools": [tool.to_mapping() for tool in self.tools],
            "resource_count": len(self.resources),
            "resources": [resource.to_safe_mapping() for resource in self.resources],
        }


@dataclass(frozen=True)
class McpCapabilityInventory:
    configured: bool
    available: bool
    servers: tuple[McpServerCapability, ...]

    @property
    def status(self) -> str:
        return "available" if self.available else "unconfigured"

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": self.status,
            "configured": self.configured,
            "available": self.available,
            "server_count": len(self.servers),
            "tool_count": sum(len(server.tools) for server in self.servers),
            "resource_count": sum(len(server.resources) for server in self.servers),
            "servers": [server.to_mapping() for server in self.servers],
        }


def build_mcp_capability_inventory(
    servers: Sequence[McpServerSpec],
) -> McpCapabilityInventory:
    if not servers:
        return McpCapabilityInventory(configured=False, available=False, servers=())
    discovered = LocalStdioMcpTransport(servers).model_tools
    discovered_resources = discover_mcp_resources(servers)
    tools_by_server: dict[str, list[McpToolCapability]] = {
        server.name: [] for server in servers
    }
    for definition in discovered:
        _, server_name, remote_name = definition.name.split(".", maxsplit=2)
        properties = definition.parameters.get("properties", {})
        assert isinstance(properties, Mapping)
        tools_by_server[server_name].append(
            McpToolCapability(
                name=remote_name,
                description=definition.description,
                input_fields=tuple(sorted(properties)),
            )
        )
    projected = tuple(
        McpServerCapability(
            name=server_name,
            tools=tuple(sorted(tools, key=lambda tool: tool.name)),
            resources=tuple(
                resource
                for resource in discovered_resources
                if resource.server_name == server_name
            ),
        )
        for server_name, tools in sorted(tools_by_server.items())
    )
    return McpCapabilityInventory(configured=True, available=True, servers=projected)


def validate_mcp_capability_selection(
    servers: Sequence[McpServerSpec],
    selected_tools: Sequence[str],
) -> tuple[str, ...]:
    normalized = normalize_mcp_allowlist(selected_tools)
    if not normalized:
        return ()
    inventory = build_mcp_capability_inventory(servers)
    available = {
        f"mcp.{server.name}.{tool.name}"
        for server in inventory.servers
        for tool in server.tools
    }
    missing = sorted(set(normalized) - available)
    if missing:
        raise ValueError(f"selected MCP tools are unavailable: {', '.join(missing)}")
    return normalized
