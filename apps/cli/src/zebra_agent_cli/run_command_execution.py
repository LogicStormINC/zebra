from __future__ import annotations

import argparse
from pathlib import Path

from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
    build_mcp_prompt_attachment,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.skills import SkillComponentIdentity
from agent_core.domain.tool_profiles import ToolProfile
from agent_runtime import (
    normalize_mcp_resource_ids,
    read_mcp_resource_attachments,
    resolve_mcp_prompt,
    validate_mcp_capability_selection,
)
from agent_security import PolicyProfile, parse_network_profile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteSkillsStateStore,
    SQLiteWorkspaceProjectionStore,
    store_initial_text_attachments,
)
from agent_tools.skills_catalog import LocalSkillCatalog
from agent_tools.skills_scope import build_scoped_skill_roots
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_cli.cli_database import (
    _database_path,
)
from zebra_agent_cli.cli_types import CliCommandResult
from zebra_agent_cli.execution import execute_durable_run, serialize_run_execution
from zebra_agent_cli.mcp_prompt_commands import parse_mcp_prompt_selection


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
    mcp_prompt_id, mcp_prompt_arguments = parse_mcp_prompt_selection(
        namespace.mcp_prompt,
        namespace.mcp_prompt_arg,
    )
    if (mcp_allowlist or mcp_resource_ids or mcp_prompt_id) and network_profile.name not in {
        NetworkProfileName.MCP_PROXY_ONLY,
        NetworkProfileName.FULL_TRUSTED_LOCAL,
    }:
        raise ValueError("MCP selections require an MCP-capable network profile")
    validate_mcp_capability_selection(settings.mcp_servers, mcp_allowlist)
    resource_attachments = read_mcp_resource_attachments(
        settings.mcp_servers,
        mcp_resource_ids,
    )
    prompt_attachments: tuple[TextAttachmentInput, ...] = ()
    if mcp_prompt_id is not None:
        resolved_prompt = resolve_mcp_prompt(
            settings.mcp_servers,
            mcp_prompt_id,
            mcp_prompt_arguments,
        )
        prompt_attachments = (
            build_mcp_prompt_attachment(
                server_name=resolved_prompt.server_name,
                prompt_id=resolved_prompt.prompt_id,
                argument_names=tuple(name for name, _ in resolved_prompt.arguments),
                messages=tuple(
                    (message.role, message.text) for message in resolved_prompt.messages
                ),
            ),
        )
    attachments = (*resource_attachments, *prompt_attachments)
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
            attachments=attachments,
        )
        session = execution_result.harness_result.session
        payload = serialize_run_execution(execution_result)
    else:
        skill_components, skill_component_identities = _skill_grant_snapshot(settings)
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
                skill_components=skill_components,
                skill_component_identities=skill_component_identities,
            )
        )
        session = bootstrap.session
        events, attachment_refs = store_initial_text_attachments(
            SQLiteArtifactPayloadStore(database_path),
            bootstrap.events,
            attachments,
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
            **({"mcp_prompt_id": mcp_prompt_id} if mcp_prompt_id is not None else {}),
            **payload,
        },
    )


def _skill_grant_snapshot(
    settings: ZebraAgentSettings,
) -> tuple[tuple[str, ...], tuple[SkillComponentIdentity, ...]]:
    roots = build_scoped_skill_roots(
        system=settings.skill_roots_system,
        admin=settings.skill_roots_admin,
        user=settings.skill_roots,
        repo=settings.skill_roots_repo,
    )
    if not roots:
        return (), ()
    metadata = LocalSkillCatalog(
        roots,
        skills_state=SQLiteSkillsStateStore(settings.skills_state_path),
    ).list()[0]
    identities = tuple(item.component_identity() for item in metadata)
    return tuple(identity.name for identity in identities), identities
