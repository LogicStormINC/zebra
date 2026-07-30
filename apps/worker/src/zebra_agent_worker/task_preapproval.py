from __future__ import annotations

from typing import TypedDict

from agent_core.domain.modeling import ModelToolDefinition
from agent_security import LocalPolicyEngine, NetworkProfile, PolicyProfile
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.task_recovery import RecoveredTask


class HarnessAuthority(TypedDict):
    mcp_allowlist: tuple[str, ...]
    preapproved_readonly_tools: tuple[str, ...]


def is_trusted_local(enabled: bool, task: RecoveredTask) -> bool:
    return enabled and not (
        task.policy_profile == PolicyProfile.READ_ONLY.value
        and task.network_profile.name.value == "mcp-proxy-only"
    )


def harness_authority(
    task: RecoveredTask,
    mcp_tools: tuple[ModelToolDefinition, ...],
) -> HarnessAuthority:
    mcp_allowlist = tuple(tool.name for tool in mcp_tools)
    return {
        "mcp_allowlist": mcp_allowlist,
        "preapproved_readonly_tools": tuple(
            name
            for name in task.preapproved_readonly_tools or ()
            if name in mcp_allowlist
        ),
    }


def build_policy_engine(
    factory: type[LocalPolicyEngine],
    task: RecoveredTask,
    network_profile: NetworkProfile,
    settings: ZebraAgentSettings,
    mcp_tools: tuple[ModelToolDefinition, ...],
    trusted_local: bool,
    allow_finos_account_changes_proposal: bool,
) -> LocalPolicyEngine:
    profile = PolicyProfile(task.policy_profile)
    authority = harness_authority(task, mcp_tools)
    if authority["preapproved_readonly_tools"]:
        return factory(
            profile=profile,
            network_profile=network_profile,
            web_search_endpoint=settings.web_search_endpoint,
            **authority,
            trusted_local=trusted_local,
            allow_finos_account_changes_proposal=allow_finos_account_changes_proposal,
        )
    return factory(
        profile=profile,
        network_profile=network_profile,
        web_search_endpoint=settings.web_search_endpoint,
        trusted_local=trusted_local,
        allow_finos_account_changes_proposal=allow_finos_account_changes_proposal,
    )
