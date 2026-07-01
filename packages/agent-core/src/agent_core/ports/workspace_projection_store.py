from typing import Protocol

from agent_core.domain.identifiers import SessionId
from agent_core.domain.workspaces import WorkspaceProjection


class WorkspaceProjectionStorePort(Protocol):
    def save_workspace(self, workspace: WorkspaceProjection) -> WorkspaceProjection: ...

    def get_workspace(self, session_id: SessionId) -> WorkspaceProjection | None: ...
