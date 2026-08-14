"""Typed default composition for the Cloud Worker entrypoint."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent_core.domain.identifiers import SessionId
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_storage import (
    CloudCompositionSettings,
    PostgresControlPlaneStores,
    postgres_control_plane_stores,
)

from zebra_agent_worker.provider_continuation_commit import (
    CloudProviderContinuationCoordinator,
)
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


@dataclass(frozen=True, slots=True)
class CloudWorkerComposition:
    """One Cloud authority bundle; it is deliberately not a local store facade."""

    stores: PostgresControlPlaneStores
    effect_dispatch: EffectDispatchPort
    projection_transaction: WorkerProjectionTransactionPort
    deployment_namespace: str
    artifact_factory: Callable[[SessionId], CloudToolOutputArtifactCoordinator]
    provider_continuation_factory: Callable[[SessionId], CloudProviderContinuationCoordinator]


def compose_cloud_worker(
    cloud: CloudCompositionSettings,
) -> CloudWorkerComposition:
    required_object_operations = (
        "put_if_absent",
        "verify",
        "read_verified",
        "read_version_verified",
        "delete_if_version",
    )
    if any(
        not callable(getattr(cloud.artifact_objects, name, None))
        for name in required_object_operations
    ):
        raise ValueError("cloud Worker requires an immutable Artifact object writer")
    stores = postgres_control_plane_stores(
        cloud.dsn,
        deployment_namespace=cloud.deployment_namespace,
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    dispatch = stores.effects
    required_dispatch = (
        "schedule_with_payload",
        "complete_with_payload",
        "mark_uncertain_with_payload",
    )
    if any(not callable(getattr(dispatch, name, None)) for name in required_dispatch):
        raise ValueError("cloud Effect dispatch must atomically link Artifact payloads")
    transaction = stores.worker_projection_transaction

    def artifact_factory(session_id: SessionId) -> CloudToolOutputArtifactCoordinator:
        return CloudToolOutputArtifactCoordinator(
            session_id,
            stores.artifact_payloads,
            cloud.artifact_objects,
        )

    def provider_factory(session_id: SessionId) -> CloudProviderContinuationCoordinator:
        return CloudProviderContinuationCoordinator(
            store=stores.provider_continuations,
            scope=cloud.continuation_scope,
            session_id=session_id,
        )

    return CloudWorkerComposition(
        stores=stores,
        effect_dispatch=dispatch,
        projection_transaction=transaction,
        deployment_namespace=stores.deployment_namespace,
        artifact_factory=artifact_factory,
        provider_continuation_factory=provider_factory,
    )
