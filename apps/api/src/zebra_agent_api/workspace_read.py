from __future__ import annotations

from agent_core.domain.workspaces import WorkspaceProjection


def serialize_workspace_projection(
    workspace: WorkspaceProjection | None,
) -> dict[str, object] | None:
    if workspace is None:
        return None
    body: dict[str, object] = {
        "workspace_root": workspace.workspace_root,
        "status": workspace.status.value,
        "current_sequence": workspace.current_sequence,
        "prepared_at": workspace.prepared_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
        "tool_profile": workspace.tool_profile.value,
        "network_profile": workspace.network_profile.value,
        "network_allowlist": list(workspace.network_allowlist),
    }
    if workspace.mcp_allowlist is not None:
        body["mcp_allowlist"] = list(workspace.mcp_allowlist)
    if workspace.preapproved_readonly_tools is not None:
        body["preapproved_readonly_tools"] = list(workspace.preapproved_readonly_tools)
    if workspace.skill_components is not None:
        body["skill_components"] = list(workspace.skill_components)
    if workspace.agent_definition is not None:
        body["agent_definition"] = workspace.agent_definition.model_dump(mode="json")
    if workspace.policy_profile is not None:
        body["policy_profile"] = workspace.policy_profile
    if workspace.last_attempt_number is not None:
        body["last_attempt_number"] = workspace.last_attempt_number
    if workspace.runtime_name is not None:
        body["runtime_name"] = workspace.runtime_name
    runtime = _runtime_body(workspace)
    if runtime is not None:
        body["runtime"] = runtime
    snapshot = _snapshot_body(workspace)
    if snapshot is not None:
        body["snapshot"] = snapshot
    return body


def _runtime_body(workspace: WorkspaceProjection) -> dict[str, object] | None:
    if workspace.runtime_spec_digest is None:
        return None
    return {
        "class": workspace.runtime_name,
        "engine": workspace.runtime_engine,
        "image": workspace.runtime_image,
        "spec_digest": workspace.runtime_spec_digest,
        "network_enforcement": workspace.runtime_network_enforcement,
        "workspace_writable": workspace.runtime_workspace_writable,
    }


def _snapshot_body(workspace: WorkspaceProjection) -> dict[str, object] | None:
    if workspace.snapshot_id is None and workspace.snapshot_path is None:
        return None
    body: dict[str, object] = {}
    if workspace.runtime_name is not None:
        body["runtime_name"] = workspace.runtime_name
    if workspace.snapshot_id is not None:
        body["snapshot_id"] = workspace.snapshot_id
    if workspace.snapshot_path is not None:
        body["snapshot_path"] = workspace.snapshot_path
    return body
