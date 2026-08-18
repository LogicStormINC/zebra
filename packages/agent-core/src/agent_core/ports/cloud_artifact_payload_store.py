from typing import Protocol

from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.cloud_artifact_requests import (
    ArtifactBeginPruneRequest,
    ArtifactCompensateRequest,
    ArtifactCompletePruneRequest,
    ArtifactFinalizeRequest,
    ArtifactManagementContext,
    ArtifactMetadataQuery,
    ArtifactReconcileQuery,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
)
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS, WorkerMutationAuthority


class CloudArtifactPayloadStorePort(Protocol):
    def reserve_for_worker(
        self,
        request: ArtifactReserveRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord: ...

    def record_object_for_worker(
        self,
        request: ArtifactRecordObjectRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord: ...

    def finalize_for_worker(
        self,
        request: ArtifactFinalizeRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord: ...

    def compensate_for_worker(
        self,
        request: ArtifactCompensateRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord: ...

    def begin_prune_for_worker(
        self,
        request: ArtifactBeginPruneRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord: ...

    def complete_prune_for_worker(
        self,
        request: ArtifactCompletePruneRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord: ...

    def finalize_reconciled(
        self,
        request: ArtifactFinalizeRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord: ...

    def compensate_reconciled(
        self,
        request: ArtifactCompensateRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord: ...

    def begin_retention_prune(
        self,
        request: ArtifactBeginPruneRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord: ...

    def complete_reconciled_prune(
        self,
        request: ArtifactCompletePruneRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord: ...

    def get_metadata(
        self,
        query: ArtifactMetadataQuery,
    ) -> CloudArtifactPayloadRecord | None: ...

    def list_reconcilable(
        self,
        query: ArtifactReconcileQuery,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> tuple[CloudArtifactPayloadRecord, ...]: ...
