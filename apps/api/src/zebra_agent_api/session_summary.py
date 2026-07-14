from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection

from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.workspace_read import serialize_workspace_projection


def serialize_session_summary(
    session: Session,
    workspace: WorkspaceProjection | None,
    *,
    include_timestamps: bool = False,
) -> dict[str, object]:
    body: dict[str, object] = {
        "session_id": str(session.session_id),
        "title": session.title,
        "status": session.status.value,
        "current_sequence": session.current_sequence,
    }
    if include_timestamps:
        body["created_at"] = session.created_at.isoformat()
        body["updated_at"] = session.updated_at.isoformat()
    serialized_workspace = serialize_workspace_projection(workspace)
    if serialized_workspace is not None:
        body["workspace"] = serialized_workspace
    approval_context = serialize_approval_context(session.approval_context)
    if approval_context is not None:
        body["approval_context"] = approval_context
    return body
