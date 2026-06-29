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
    }
    if workspace.policy_profile is not None:
        body["policy_profile"] = workspace.policy_profile
    if workspace.last_attempt_number is not None:
        body["last_attempt_number"] = workspace.last_attempt_number
    if workspace.snapshot_id is not None or workspace.snapshot_path is not None:
        snapshot: dict[str, object] = {}
        if workspace.runtime_name is not None:
            snapshot["runtime_name"] = workspace.runtime_name
        if workspace.snapshot_id is not None:
            snapshot["snapshot_id"] = workspace.snapshot_id
        if workspace.snapshot_path is not None:
            snapshot["snapshot_path"] = workspace.snapshot_path
        body["snapshot"] = snapshot
    return body
