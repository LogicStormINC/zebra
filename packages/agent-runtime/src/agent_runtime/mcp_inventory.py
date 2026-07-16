from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_runtime.mcp_protocol import McpServerSpec
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

    def to_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tool_count": len(self.tools),
            "tools": [tool.to_mapping() for tool in self.tools],
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
            "servers": [server.to_mapping() for server in self.servers],
        }


def build_mcp_capability_inventory(
    servers: Sequence[McpServerSpec],
) -> McpCapabilityInventory:
    if not servers:
        return McpCapabilityInventory(configured=False, available=False, servers=())
    discovered = LocalStdioMcpTransport(servers).model_tools
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
        )
        for server_name, tools in sorted(tools_by_server.items())
    )
    return McpCapabilityInventory(configured=True, available=True, servers=projected)
