"""Resolve local versus Cloud-only Worker storage dependencies once."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.application import (
    MemoryCandidateExtractionService,
    MemoryCandidatePromotionService,
)
from agent_core.ports import (
    ArtifactPayloadReadPort,
    ArtifactPayloadStorePort,
    EffectLedgerPort,
    GovernedMemoryStorePort,
    MemoryReadPort,
    ProviderContinuationStorePort,
    WorkerProjectionTransactionPort,
)
from agent_storage import (
    ControlPlaneStores,
    PostgresControlPlaneStores,
    sqlite_control_plane_stores,
)

from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.tool_run_index import ToolRunIndexer


def compose_recovery(
    stores: ControlPlaneStores | PostgresControlPlaneStores,
    transaction: WorkerProjectionTransactionPort | None,
    namespace: str | None,
    artifacts: ArtifactPayloadStorePort | None,
) -> tuple[ModelCallIndexer, ToolRunIndexer, SessionRecoveryService]:
    models = ModelCallIndexer(stores.model_calls)
    tools = ToolRunIndexer(stores.tool_runs, artifacts)
    recovery = SessionRecoveryService(
        stores.events,
        stores.sessions,
        stores.workspaces,
        worker_projection_transaction=transaction,
        deployment_namespace=namespace,
        model_call_indexer=models if transaction else None,
        tool_run_indexer=tools if transaction else None,
        session_recovery_store=(
            stores.session_recovery if isinstance(stores, PostgresControlPlaneStores) else None
        ),
    )
    return models, tools, recovery


@dataclass(frozen=True, slots=True)
class ExecutionStorage:
    stores: ControlPlaneStores | PostgresControlPlaneStores
    artifact_payload_store: ArtifactPayloadStorePort | None
    artifact_payload_reader: ArtifactPayloadReadPort
    provider_continuation_store: ProviderContinuationStorePort | None
    memory_store: MemoryReadPort
    cloud_memory_store: GovernedMemoryStorePort | None
    memory_extraction_service: MemoryCandidateExtractionService | None
    memory_promotion_service: MemoryCandidatePromotionService | None
    effect_ledger: EffectLedgerPort | None
    deployment_namespace: str | None


def resolve_execution_storage(
    database_path: Path,
    stores: ControlPlaneStores | PostgresControlPlaneStores | None,
) -> ExecutionStorage:
    active = stores or sqlite_control_plane_stores(database_path)
    if isinstance(active, PostgresControlPlaneStores):
        return ExecutionStorage(
            stores=active,
            artifact_payload_store=None,
            artifact_payload_reader=active.artifact_payload_reader,
            provider_continuation_store=None,
            memory_store=active.memories,
            cloud_memory_store=active.memories,
            memory_extraction_service=None,
            memory_promotion_service=None,
            effect_ledger=None,
            deployment_namespace=active.deployment_namespace,
        )
    return ExecutionStorage(
        stores=active,
        artifact_payload_store=active.artifact_payloads,
        artifact_payload_reader=active.artifact_payload_reader,
        provider_continuation_store=active.provider_continuations,
        memory_store=active.memories,
        cloud_memory_store=None,
        memory_extraction_service=MemoryCandidateExtractionService(active.memories),
        memory_promotion_service=MemoryCandidatePromotionService(active.memories),
        effect_ledger=active.effects,
        deployment_namespace=None,
    )
