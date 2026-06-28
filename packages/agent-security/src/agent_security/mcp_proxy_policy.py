from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_core.domain.tools import ToolCall

from agent_security.network_profile import (
    DEFAULT_NETWORK_PROFILE,
    NetworkProfile,
    NetworkProfileName,
)


class ToolEgressRoute(StrEnum):
    LOCAL = "local"
    MCP_PROXY = "mcp_proxy"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ToolEgressMetadata:
    tool_name: str
    route: ToolEgressRoute
    network_profile: str
    target: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("tool_name must not be blank")
        if not self.network_profile.strip():
            raise ValueError("network_profile must not be blank")

    def to_mapping(self) -> dict[str, str]:
        mapping = {
            "tool_name": self.tool_name,
            "route": self.route.value,
            "network_profile": self.network_profile,
        }
        if self.target is not None:
            mapping["target"] = self.target
        if self.reason:
            mapping["reason"] = self.reason
        return mapping


def classify_tool_egress(
    tool_call: ToolCall,
    *,
    network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE,
) -> ToolEgressMetadata:
    normalized_name = tool_call.name.strip()
    target = _mcp_target(normalized_name)
    if target is None:
        return ToolEgressMetadata(
            tool_name=normalized_name,
            route=ToolEgressRoute.LOCAL,
            network_profile=network_profile.name.value,
            reason="builtin or local tool path",
        )
    if network_profile.name in (
        NetworkProfileName.MCP_PROXY_ONLY,
        NetworkProfileName.FULL_TRUSTED_LOCAL,
    ):
        return ToolEgressMetadata(
            tool_name=normalized_name,
            route=ToolEgressRoute.MCP_PROXY,
            network_profile=network_profile.name.value,
            target=target,
            reason="mcp tool must route through proxy contract",
        )
    return ToolEgressMetadata(
        tool_name=normalized_name,
        route=ToolEgressRoute.BLOCKED,
        network_profile=network_profile.name.value,
        target=target,
        reason=f"network profile {network_profile.name.value} does not allow mcp proxy egress",
    )


def _mcp_target(tool_name: str) -> str | None:
    parts = tool_name.split(".")
    if len(parts) != 3 or parts[0] != "mcp":
        return None
    server_name = parts[1].strip()
    remote_tool = parts[2].strip()
    if not server_name or not remote_tool:
        return None
    return f"{server_name}.{remote_tool}"
