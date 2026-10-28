from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority


class WorkerCommitConfirmationPending(RuntimeError):
    """An atomic write timed out and its exact outcome could not be confirmed; never replay it."""


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

    def project_persisted_worker_event(
        self,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
        *,
        authority: WorkerMutationAuthority,
    ) -> WorkerProjectionCommitResult:
        """Fence and project an Event already committed by another aggregate."""


@runtime_checkable
class WorkerProjectionBatchPort(Protocol):
    """Optional bounded canonical-tail projection; not an Event append shortcut."""

    def project_persisted_worker_events(
        self, events: tuple[SessionEvent, ...], session: Session, workspace: WorkspaceProjection,
        *, authority: WorkerMutationAuthority,
    ) -> WorkerProjectionCommitResult: ...
