from __future__ import annotations

from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.tool_profiles import ToolProfile
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_attachment_persistence import persist_initial_attachments
from zebra_agent_api.session_payloads import CreateSessionPayload


def create_queued_session(
    stores: ControlPlaneStores,
    parsed: CreateSessionPayload,
    *,
    host_context: HostContextEnvelope | None = None,
    definition_snapshot: AgentDefinitionSnapshot | None = None,
) -> ApiResponse:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=str(parsed["title"]),
            user_input=str(parsed["prompt"]),
            workspace_root=_workspace_root(str(parsed["workspace"])),
            policy_profile=str(parsed["policy_profile"]),
            tool_profile=ToolProfile(str(parsed["tool_profile"])),
            network_profile=str(parsed["network_profile"]),
            network_allowlist=tuple(parsed["network_allowlist"]),
            mcp_allowlist=tuple(parsed["mcp_allowlist"]),
            history_session_ids=parsed["history_session_ids"],
            max_model_calls=parsed["max_model_calls"],
            max_tool_calls=parsed["max_tool_calls"],
            host_context=host_context,
            definition_snapshot=definition_snapshot,
        )
    )
    events, attachment_refs = persist_initial_attachments(
        stores.artifact_payloads,
        tuple(bootstrap.events),
        parsed["attachments"],
    )
    for event in events:
        stores.events.append(event)
    stores.sessions.save_session(bootstrap.session)
    stores.workspaces.save_workspace(rebuild_workspace(list(events)))
    return ApiResponse(
        status_code=201,
        body={
            "session_id": str(bootstrap.session.session_id),
            "title": str(parsed["title"]),
            "prompt": str(parsed["prompt"]),
            "workspace": str(parsed["workspace"]),
            "executed": False,
            "status": bootstrap.session.status.value,
            "tool_profile": str(parsed["tool_profile"]),
            "max_model_calls": parsed["max_model_calls"],
            "max_tool_calls": parsed["max_tool_calls"],
            "network_profile": str(parsed["network_profile"]),
            "network_allowlist": parsed["network_allowlist"],
            "mcp_allowlist": parsed["mcp_allowlist"],
            "mcp_resource_ids": parsed["mcp_resource_ids"],
            **(
                {"history_session_ids": list(parsed["history_session_ids"])}
                if parsed["history_session_ids"] is not None
                else {}
            ),
            **(
                {"mcp_prompt_id": parsed["mcp_prompt_id"]}
                if parsed["mcp_prompt_id"] is not None
                else {}
            ),
            "attachments": [ref.to_mapping() for ref in attachment_refs],
        },
    )


def _workspace_root(reference: str) -> Path:
    """Control-plane references keep their uri shape; plain paths resolve."""
    if reference.startswith("workspace://"):
        return Path(reference)
    return Path(reference).expanduser().resolve()
