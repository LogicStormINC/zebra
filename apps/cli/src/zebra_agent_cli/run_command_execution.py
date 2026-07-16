from __future__ import annotations

import argparse
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.tool_profiles import ToolProfile
from agent_runtime import (
    normalize_mcp_resource_ids,
    read_mcp_resource_attachments,
    validate_mcp_capability_selection,
)
from agent_security import PolicyProfile, parse_network_profile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    store_initial_text_attachments,
)
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_cli.cli_database import (
    _database_path,
)
from zebra_agent_cli.cli_types import CliCommandResult
from zebra_agent_cli.execution import execute_durable_run, serialize_run_execution


def _run_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    database_path = _database_path(namespace.database, settings)
    workspace = Path(namespace.workspace)
    network_profile = parse_network_profile(
        namespace.network_profile,
        domain_allowlist=namespace.network_allowlist,
    )
    mcp_allowlist = normalize_mcp_allowlist(namespace.mcp_tool)
    mcp_resource_ids = normalize_mcp_resource_ids(namespace.mcp_resource)
    if (mcp_allowlist or mcp_resource_ids) and network_profile.name not in {
        NetworkProfileName.MCP_PROXY_ONLY,
        NetworkProfileName.FULL_TRUSTED_LOCAL,
    }:
        raise ValueError("MCP selections require an MCP-capable network profile")
    validate_mcp_capability_selection(settings.mcp_servers, mcp_allowlist)
    resource_attachments = read_mcp_resource_attachments(
        settings.mcp_servers,
        mcp_resource_ids,
    )
    if namespace.execute:
        execution_result = execute_durable_run(
            prompt=namespace.prompt,
            title=namespace.title,
            workspace_root=workspace.expanduser().resolve(),
            database_path=database_path,
            settings=settings,
            policy_profile=PolicyProfile(namespace.policy_profile),
            tool_profile=ToolProfile(namespace.tool_profile),
            network_profile=network_profile,
            mcp_allowlist=mcp_allowlist,
            attachments=resource_attachments,
        )
        session = execution_result.harness_result.session
        payload = serialize_run_execution(execution_result)
    else:
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title=namespace.title,
                user_input=namespace.prompt,
                workspace_root=workspace.expanduser().resolve(),
                policy_profile=namespace.policy_profile,
                tool_profile=ToolProfile(namespace.tool_profile),
                network_profile=network_profile.name.value,
                network_allowlist=network_profile.domain_allowlist,
                mcp_allowlist=mcp_allowlist,
            )
        )
        session = bootstrap.session
        events, attachment_refs = store_initial_text_attachments(
            SQLiteArtifactPayloadStore(database_path),
            bootstrap.events,
            resource_attachments,
        )
        event_store = SQLiteEventStore(database_path)
        for event in events:
            event_store.append(event)
        SQLiteProjectionStore(database_path).save_session(session)
        SQLiteWorkspaceProjectionStore(database_path).save_workspace(
            rebuild_workspace(list(events))
        )
        payload = {
            "executed": False,
            "status": session.status.value,
            "tool_profile": namespace.tool_profile,
            "network_profile": network_profile.name.value,
            "network_allowlist": list(network_profile.domain_allowlist),
            "mcp_allowlist": list(mcp_allowlist),
            "attachments": [attachment.to_mapping() for attachment in attachment_refs],
        }
    return CliCommandResult(
        command="run",
        payload={
            "session_id": str(session.session_id),
            "title": namespace.title,
            "prompt": namespace.prompt,
            "workspace": str(workspace),
            "database": str(database_path),
            "mcp_resource_ids": list(mcp_resource_ids),
            **payload,
        },
    )
