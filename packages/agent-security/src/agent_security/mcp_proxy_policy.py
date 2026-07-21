from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_core.domain.tools import ToolCall
from agent_core.domain.web import WebTargetError, parse_web_target
from agent_core.domain.web_search import (
    WebSearchInputError,
    parse_web_search_input as parse_legacy_web_search_input,
)
from agent_tools.search_pipeline import SearchInputError, parse_search_query

from agent_security.network_profile import (
    DEFAULT_NETWORK_PROFILE,
    NetworkProfile,
    NetworkProfileName,
)


class ToolEgressRoute(StrEnum):
    LOCAL = "local"
    MCP_PROXY = "mcp_proxy"
    WEB_GATEWAY = "web_gateway"
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
    web_search_endpoint: str | None = None,
    web_pipeline_v2: bool = False,
) -> ToolEgressMetadata:
    normalized_name = tool_call.name.strip()
    if normalized_name == "web.fetch":
        return _classify_web_egress(tool_call, network_profile)
    if normalized_name == "web.search":
        return _classify_web_search_egress(
            tool_call,
            network_profile,
            web_search_endpoint,
            web_pipeline_v2=web_pipeline_v2,
        )
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


def _classify_web_egress(
    tool_call: ToolCall,
    network_profile: NetworkProfile,
) -> ToolEgressMetadata:
    try:
        target = parse_web_target(tool_call.arguments.get("url"))
    except WebTargetError as exc:
        return ToolEgressMetadata(
            tool_name=tool_call.name,
            route=ToolEgressRoute.BLOCKED,
            network_profile=network_profile.name.value,
            reason=str(exc),
        )
    if network_profile.name is NetworkProfileName.FULL_TRUSTED_LOCAL or (
        network_profile.name is NetworkProfileName.DOMAIN_ALLOWLIST
        and target.hostname in network_profile.domain_allowlist
    ):
        return ToolEgressMetadata(
            tool_name=tool_call.name,
            route=ToolEgressRoute.WEB_GATEWAY,
            network_profile=network_profile.name.value,
            target=target.hostname,
            reason="web target matches the durable domain allowlist",
        )
    return ToolEgressMetadata(
        tool_name=tool_call.name,
        route=ToolEgressRoute.BLOCKED,
        network_profile=network_profile.name.value,
        target=target.hostname,
        reason="web target is not allowed by the durable network profile",
    )


def _classify_web_search_egress(
    tool_call: ToolCall,
    network_profile: NetworkProfile,
    endpoint: str | None,
    *,
    web_pipeline_v2: bool,
) -> ToolEgressMetadata:
    try:
        search_query, search_limit = _parse_web_search_input_for_policy(
            tool_call.arguments,
            web_pipeline_v2=web_pipeline_v2,
        )
        target = parse_web_target(endpoint)
    except (WebSearchInputError, SearchInputError, WebTargetError) as exc:
        return ToolEgressMetadata(
            tool_name=tool_call.name,
            route=ToolEgressRoute.BLOCKED,
            network_profile=network_profile.name.value,
            reason=str(exc),
        )
    if network_profile.name is NetworkProfileName.FULL_TRUSTED_LOCAL or (
        network_profile.name is NetworkProfileName.DOMAIN_ALLOWLIST
        and target.hostname in network_profile.domain_allowlist
    ):
        return ToolEgressMetadata(
            tool_name=tool_call.name,
            route=ToolEgressRoute.WEB_GATEWAY,
            network_profile=network_profile.name.value,
            target=target.hostname,
            reason=(
                "configured search endpoint matches the durable domain allowlist; "
                f"query={search_query!r}; limit={search_limit}; side_effect=read_only"
            ),
        )
    return ToolEgressMetadata(
        tool_name=tool_call.name,
        route=ToolEgressRoute.BLOCKED,
        network_profile=network_profile.name.value,
        target=target.hostname,
        reason="configured search endpoint is not allowed by the durable network profile",
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


def _parse_web_search_input_for_policy(
    arguments: object,
    *,
    web_pipeline_v2: bool,
) -> tuple[str, int]:
    if web_pipeline_v2:
        parsed = parse_search_query(arguments)
    else:
        parsed = parse_legacy_web_search_input(arguments)
    return parsed.query, parsed.limit
