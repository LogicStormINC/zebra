from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority


class WorkspaceProjectionStorePort(Protocol):
    def save_workspace(self, workspace: WorkspaceProjection) -> WorkspaceProjection: ...

    def get_workspace(self, session_id: SessionId) -> WorkspaceProjection | None: ...


@dataclass(frozen=True, slots=True)
class WorkerProjectionCommitResult:
    """Canonical Event and projections accepted by durable storage."""

    event: SessionEvent
    session: Session
    workspace: WorkspaceProjection


class WorkerProjectionTransactionPort(Protocol):
    """Commit one Worker Event and its primary projections atomically."""

    def commit_worker_event(
        self,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
        *,
        authority: WorkerMutationAuthority,
    ) -> WorkerProjectionCommitResult: ...
