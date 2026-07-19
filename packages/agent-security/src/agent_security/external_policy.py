from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall

from agent_security.mcp_proxy_policy import ToolEgressMetadata, ToolEgressRoute


def external_read_allow_decision(
    *,
    policy_profile: str,
    tool_call: ToolCall,
    egress: ToolEgressMetadata,
) -> PolicyDecision:
    target = egress.target or egress.tool_name
    return PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        reason=(
            f"{egress.tool_name} is allowed for bounded read-only Web retrieval to "
            f"{target} under durable network profile {egress.network_profile}"
        ),
        policy_profile=policy_profile,
        route=egress.route.value,
        target=egress.target,
        network_profile=egress.network_profile,
        scope=_external_scope(tool_call, egress),
    )


def external_approval_decision(
    *,
    policy_profile: str,
    tool_call: ToolCall,
    egress: ToolEgressMetadata,
) -> PolicyDecision:
    target = egress.target or egress.tool_name
    route_label = (
        "proxy-routed external tool execution"
        if egress.route is ToolEgressRoute.MCP_PROXY
        else "gateway-routed external Web retrieval"
    )
    return PolicyDecision(
        decision=PolicyDecisionType.REQUIRE_APPROVAL,
        reason=(
            f"{egress.tool_name} requires approval for {route_label} to {target} "
            f"under network profile {egress.network_profile}"
        ),
        policy_profile=policy_profile,
        route=egress.route.value,
        target=egress.target,
        network_profile=egress.network_profile,
        scope=_external_scope(tool_call, egress),
    )


def blocked_route_reason(egress: ToolEgressMetadata) -> str:
    target = egress.target or egress.tool_name
    denied_capability = (
        "mcp proxy egress"
        if egress.tool_name.startswith("mcp.")
        else "the requested egress"
    )
    return (
        f"{egress.tool_name} is blocked on external route {target} because network profile "
        f"{egress.network_profile} does not allow {denied_capability}"
    )


def _external_scope(
    tool_call: ToolCall,
    egress: ToolEgressMetadata,
) -> tuple[str, ...]:
    entries = [
        f"tool:{tool_call.name}",
        f"route:{egress.route.value}",
        f"network_profile:{egress.network_profile}",
    ]
    if egress.target is not None:
        entries.append(f"target:{egress.target}")
    if tool_call.name == "web.search":
        query = tool_call.arguments.get("query")
        limit = tool_call.arguments.get("limit", 5)
        if isinstance(query, str):
            entries.append(f"query:{query.strip()}")
        if isinstance(limit, int) and not isinstance(limit, bool):
            entries.append(f"limit:{limit}")
        entries.append("side_effect:read_only")
    return tuple(entries)
