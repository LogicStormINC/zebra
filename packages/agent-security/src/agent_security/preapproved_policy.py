from __future__ import annotations

from typing import TYPE_CHECKING

from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.policies import PolicyDecision
from agent_core.domain.tools import ToolCall

from agent_security.external_policy import external_preapproved_read_allow_decision
from agent_security.mcp_proxy_policy import ToolEgressMetadata, ToolEgressRoute
from agent_security.network_profile import NetworkProfileName

if TYPE_CHECKING:
    from agent_security.policy import LocalPolicyEngine


def normalize_preapproved_mcp_authority(
    mcp_allowlist: tuple[str, ...],
    preapproved_readonly_tools: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    mcp_allowlist = normalize_mcp_allowlist(mcp_allowlist)
    preapproved_readonly_tools = normalize_mcp_allowlist(preapproved_readonly_tools)
    if not set(preapproved_readonly_tools) <= set(mcp_allowlist):
        raise ValueError("preapproved read-only tools must be in the MCP allowlist")
    return mcp_allowlist, preapproved_readonly_tools


def preapproved_readonly_mcp_decision(
    policy: LocalPolicyEngine,
    tool_call: ToolCall,
    egress: ToolEgressMetadata,
) -> PolicyDecision | None:
    if not (
        policy.profile.value == "read_only"
        and policy.network_profile.name is NetworkProfileName.MCP_PROXY_ONLY
        and egress.route is ToolEgressRoute.MCP_PROXY
        and tool_call.name in policy.mcp_allowlist
        and tool_call.name in policy.preapproved_readonly_tools
    ):
        return None
    return external_preapproved_read_allow_decision(
        policy_profile=policy.profile.value,
        tool_call=tool_call,
        egress=egress,
    )
