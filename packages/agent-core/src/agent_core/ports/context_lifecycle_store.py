from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import (
    AdministrativeMutationCAS,
    WorkerMutationAuthority,
)


@dataclass(frozen=True)
class StoredContextCapsule:
    artifact_id: ArtifactId
    session_id: SessionId
    capsule: ContextCapsule
    payload_sha256: str
    event: SessionEvent
    compaction_event: SessionEvent | None = None


@dataclass(frozen=True)
class ContextLifecycleCommitResult:
    """Canonical two-Event Context aggregate commit."""

    stored_capsule: StoredContextCapsule
    compaction_event: SessionEvent
    session: Session
    workspace: WorkspaceProjection


class ContextLifecycleStorePort(Protocol):
    def commit_worker_compaction(
        self,
        *,
        authority: WorkerMutationAuthority,
        session: Session,
        workspace: WorkspaceProjection,
        capsule: ContextCapsule,
        validation_context: ContextCapsuleValidationContext,
        expected_active_capsule_id: str | None,
        compaction_event: SessionEvent,
    ) -> ContextLifecycleCommitResult: ...

    def commit_administrative_activation(
        self,
        *,
        authority: AdministrativeMutationCAS,
        session: Session,
        workspace: WorkspaceProjection,
        capsule_id: str,
        expected_active_capsule_id: str | None,
        event: SessionEvent,
    ) -> ContextLifecycleCommitResult: ...

    def persist_capsule_and_advance(
        self,
        *,
        session_id: SessionId,
        capsule: ContextCapsule,
        validation_context: ContextCapsuleValidationContext,
        sequence: int,
        expected_active_capsule_id: str | None,
        compaction_event: SessionEvent | None = None,
        created_at: datetime | None = None,
    ) -> StoredContextCapsule: ...

    def get_capsule(self, capsule_id: str) -> StoredContextCapsule | None: ...

    def get_active_capsule(self, session_id: SessionId) -> StoredContextCapsule | None: ...

    def activate_capsule(
        self,
        *,
        session_id: SessionId,
        capsule_id: str,
        expected_active_capsule_id: str | None,
        event: SessionEvent,
    ) -> StoredContextCapsule: ...
