"""Explicit PostgreSQL cloud storage composition without changing local stores."""

from dataclasses import dataclass

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.ports import (
    ArtifactPayloadObjectReadPort,
    CloudControlPlane,
    ModelCallStorePort,
    ToolRunStorePort,
    WorkerProjectionTransactionPort,
)

from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader
from agent_storage.postgres import (
    PostgresAgentTaskStore,
    PostgresCloudArtifactPayloadStore,
    PostgresContextLifecycleStore,
    PostgresContextMaterializationStore,
    PostgresDeliveryAuditStore,
    PostgresEffectDispatchStore,
    PostgresEventStore,
    PostgresGovernedMemoryStore,
    PostgresHandoffDispatchStore,
    PostgresIdempotencyStore,
    PostgresLeaseStore,
    PostgresModelToolProjectionStore,
    PostgresProjectionStore,
    PostgresProviderContinuationStore,
    PostgresSessionArtifactReadStore,
    PostgresSessionHandoffStore,
    PostgresSessionHistory,
    PostgresWorkspaceProjectionStore,
)
from agent_storage.postgres_model_tool_compat import (
    PostgresModelCallProjectionAdapter,
    PostgresToolRunProjectionAdapter,
)


@dataclass(frozen=True, slots=True)
class PostgresControlPlaneStores(CloudControlPlane):
    """Concrete cloud composition; the local ``ControlPlaneStores`` is untouched.

    ``model_calls`` and ``tool_runs`` are compatibility views only. Their source
    remains the single Event-derived ``model_tool_projections`` adapter.
    """

    @property
    def model_calls(self) -> ModelCallStorePort:
        return PostgresModelCallProjectionAdapter(self.model_tool_projections)

    @property
    def tool_runs(self) -> ToolRunStorePort:
        return PostgresToolRunProjectionAdapter(self.model_tool_projections)

    @property
    def legacy_artifact_control_enabled(self) -> bool:
        return False

    @property
    def worker_projection_transaction(self) -> WorkerProjectionTransactionPort:
        if not isinstance(self.workspaces, PostgresWorkspaceProjectionStore):
            raise ValueError("cloud control plane requires PostgreSQL Worker projections")
        return self.workspaces


def postgres_control_plane_stores(
    dsn: str,
    *,
    deployment_namespace: str,
    memory_cursor_signing_key: bytes,
    artifact_objects: ArtifactPayloadObjectReadPort,
    history_scope: OpaqueAuthorityScope,
    continuation_scope: OpaqueAuthorityScope,
) -> PostgresControlPlaneStores:
    """Build one namespace-bound PostgreSQL cloud bundle without running DDL."""
    if not dsn.strip():
        raise ValueError("PostgreSQL DSN must not be blank")
    if len(memory_cursor_signing_key) < 32:
        raise ValueError("Memory scan cursor signing key must contain at least 32 bytes")
    if artifact_objects is None:
        raise ValueError("cloud artifact object reader is required")

    events = PostgresEventStore(dsn, deployment_namespace=deployment_namespace)
    sessions = PostgresProjectionStore(dsn, deployment_namespace=deployment_namespace)
    model_tools = PostgresModelToolProjectionStore(dsn, deployment_namespace=deployment_namespace)
    artifact_payloads = PostgresCloudArtifactPayloadStore(
        dsn, deployment_namespace=deployment_namespace
    )
    return PostgresControlPlaneStores(
        deployment_namespace=deployment_namespace,
        events=events,
        sessions=sessions,
        workspaces=PostgresWorkspaceProjectionStore(dsn, deployment_namespace=deployment_namespace),
        tasks=PostgresAgentTaskStore(dsn, deployment_namespace=deployment_namespace),
        leases=PostgresLeaseStore(dsn, deployment_namespace=deployment_namespace),
        context_lifecycle=PostgresContextLifecycleStore(
            dsn, deployment_namespace=deployment_namespace
        ),
        context_materialization=PostgresContextMaterializationStore(
            dsn, deployment_namespace=deployment_namespace
        ),
        handoffs=PostgresSessionHandoffStore(dsn, deployment_namespace=deployment_namespace),
        handoff_dispatch=PostgresHandoffDispatchStore(
            dsn, deployment_namespace=deployment_namespace
        ),
        idempotency=PostgresIdempotencyStore(dsn, deployment_namespace=deployment_namespace),
        effects=PostgresEffectDispatchStore(dsn, deployment_namespace=deployment_namespace),
        memories=PostgresGovernedMemoryStore(
            dsn,
            deployment_namespace=deployment_namespace,
            cursor_signing_key=memory_cursor_signing_key,
        ),
        artifact_payloads=artifact_payloads,
        artifact_payload_reader=CloudArtifactPayloadReader(
            artifact_payloads,
            artifact_objects,
            deployment_namespace=deployment_namespace,
        ),
        model_tool_projections=model_tools,
        artifacts=PostgresSessionArtifactReadStore(dsn, deployment_namespace=deployment_namespace),
        provider_continuations=PostgresProviderContinuationStore(
            dsn,
            deployment_namespace=deployment_namespace,
            scope=continuation_scope,
        ),
        session_history=PostgresSessionHistory(
            dsn,
            deployment_namespace=deployment_namespace,
            scope=history_scope,
        ),
        delivery_audit=PostgresDeliveryAuditStore(dsn, deployment_namespace=deployment_namespace),
    )
