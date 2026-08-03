"""Cloud-only authority contract for provider continuation payloads."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_continuation import (
    CloudProviderContinuationArtifact,
    ProviderContinuationRef,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import (
    AdministrativeMutationCAS,
    WorkerMutationAuthority,
)


@dataclass(frozen=True, slots=True)
class LoadedCloudProviderContinuation:
    artifact: CloudProviderContinuationArtifact
    opaque_payload: bytes


@dataclass(frozen=True, slots=True)
class CloudProviderContinuationCommitResult:
    artifact: CloudProviderContinuationArtifact
    event: SessionEvent
    session: Session
    workspace: WorkspaceProjection


@dataclass(frozen=True, slots=True)
class ProviderContinuationSweepReceipt:
    operation_id: UUID
    authority_issuer: str
    namespace_id: str
    deployment_namespace: str
    expired_continuation_ids: tuple[str, ...]
    recorded_at: datetime


class CloudProviderContinuationStorePort(Protocol):
    """Fenced cloud aggregate contract; local SQLite is intentionally separate."""

    def commit_worker_selection(
        self,
        *,
        scope: OpaqueAuthorityScope,
        authority: WorkerMutationAuthority,
        continuation_id: str,
        session: Session,
        workspace: WorkspaceProjection,
        reference: ProviderContinuationRef,
        opaque_payload: bytes,
        maximum_ttl_seconds: int | None,
        selection_event: SessionEvent,
    ) -> CloudProviderContinuationCommitResult: ...

    def load_compatible(
        self,
        continuation_id: str,
        *,
        scope: OpaqueAuthorityScope,
        session_id: SessionId,
        provider: str,
        model_name: str,
        capability_version: str,
        as_of: datetime | None = None,
    ) -> LoadedCloudProviderContinuation | None: ...

    def delete_for_worker(
        self,
        continuation_id: str,
        *,
        scope: OpaqueAuthorityScope,
        authority: WorkerMutationAuthority,
        idempotency_key: str,
        deleted_at: datetime | None = None,
    ) -> CloudProviderContinuationArtifact | None: ...

    def sweep_expired(
        self,
        *,
        scope: OpaqueAuthorityScope,
        authority: AdministrativeMutationCAS,
        operation_id: UUID,
        operator_id: str,
        reason: str,
        limit: int = 100,
        as_of: datetime | None = None,
    ) -> ProviderContinuationSweepReceipt: ...
