from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import httpx
from agent_core.application import SessionTitleService
from agent_core.domain.identifiers import SessionId
from agent_core.ports import (
    EffectDispatchPort,
    GovernedMemoryStorePort,
    WorkerProjectionTransactionPort,
)
from agent_integrations import build_model_gateway
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    PostgresControlPlaneStores,
    cloud_composition_from_environment,
)
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import SkillPublicationService
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.client_effect_runtime import compose_client_runtime
from zebra_agent_worker.cloud_composition import CloudWorkerComposition, compose_cloud_worker
from zebra_agent_worker.cloud_memory_recovery import (
    CloudMemoryFinalizationRecovery,
)
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.control import SessionControlService
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.live_event_runtime import configure_live_event_delivery
from zebra_agent_worker.mcp_composition import compose_worker_mcp
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.provider_configuration import model_provider_settings
from zebra_agent_worker.provider_continuation_commit import (
    CloudProviderContinuationCoordinator,
)
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.tool_run_index import ToolRunIndexer
from zebra_agent_worker.worker_loop_service import (
    WorkerLoopCycleResult as WorkerLoopCycleResult,
)
from zebra_agent_worker.worker_loop_service import (
    WorkerLoopRunResult as WorkerLoopRunResult,
)
from zebra_agent_worker.worker_loop_service import (
    WorkerLoopService as WorkerLoopService,
)
from zebra_agent_worker.worker_loop_service import (
    _task_binding_id,
)
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory
from zebra_agent_worker.worker_skill_catalog import WorkerSkillCatalogSource


def build_worker_loop_service(
    *,
    database_path: Path,
    settings: ZebraAgentSettings,
    sleep: Callable[[float], None] = time.sleep,
    stores: ControlPlaneStores | None = None,
    cloud_composition: CloudCompositionSettings | None = None,
    cloud_worker_composition: CloudWorkerComposition | None = None,
    effect_dispatch: EffectDispatchPort | None = None,
    worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
    deployment_namespace: str | None = None,
    cloud_provider_continuation_factory: Callable[[SessionId], CloudProviderContinuationCoordinator]
    | None = None,
    model_http_client: httpx.Client | None = None,
) -> WorkerLoopService:
    client_runtime = None
    if settings.mcp_credentials.worker_enabled and settings.storage_authority != "postgresql":
        raise ValueError("cloud MCP Worker requires PostgreSQL cloud composition")
    if settings.cloud_skill_worker_enabled and settings.storage_authority != "postgresql":
        raise ValueError("cloud Skill Worker requires PostgreSQL cloud composition")
    if settings.cloud_skill_worker_enabled and not settings.cloud_extension_worker_enabled:
        raise ValueError("cloud Skill Worker requires extension snapshot recovery")
    if settings.storage_authority == "postgresql":
        if stores is not None:
            raise ValueError("cloud Worker requires CloudWorkerComposition, not ControlPlaneStores")
        if any(
            value is not None
            for value in (
                effect_dispatch,
                worker_projection_transaction,
                deployment_namespace,
                cloud_provider_continuation_factory,
            )
        ):
            raise ValueError("cloud Worker dependencies must come from one CloudWorkerComposition")
        cloud_bundle = cloud_worker_composition or compose_cloud_worker(
            cloud_composition or cloud_composition_from_environment()
        )
        if settings.cloud_skill_worker_enabled and (
            cloud_bundle.extensions is None or cloud_bundle.skill_objects is None
        ):
            raise ValueError("cloud Skill Worker dependencies are unavailable")
        active_extension_store = (
            cloud_bundle.extension_snapshots if settings.cloud_extension_worker_enabled else None
        )
        if settings.cloud_skill_worker_enabled:
            assert cloud_bundle.extensions is not None and cloud_bundle.skill_objects is not None
            active_extension_skills = WorkerSkillCatalogSource(
                cloud_bundle.extensions, cloud_bundle.skill_objects,
                SkillPublicationService(
                    PostgresSkillPublicationStore(
                        cloud_bundle.dsn, deployment_namespace=cloud_bundle.deployment_namespace,
                    ), cloud_bundle.skill_objects, cloud_bundle.deployment_namespace,
                ) if cloud_bundle.dsn else None,
            )
        else:
            active_extension_skills = None
        active_stores: ControlPlaneStores | PostgresControlPlaneStores = cloud_bundle.stores
        cloud_memory_store: GovernedMemoryStorePort | None = cloud_bundle.stores.memories
        active_transaction: WorkerProjectionTransactionPort | None = (
            cloud_bundle.projection_transaction
        )
        active_namespace: str | None = cloud_bundle.deployment_namespace
        active_dispatch: EffectDispatchPort | None = cloud_bundle.effect_dispatch
        active_artifact_factory = cloud_bundle.artifact_factory
        active_workspace_resolver_factory = cloud_bundle.workspace_resolver_factory
        active_provider_factory: (
            Callable[[SessionId], CloudProviderContinuationCoordinator] | None
        ) = cloud_bundle.provider_continuation_factory
        active_authority_resolver = cloud_bundle.authority_resolver
        active_authority_scope_provider = cloud_bundle.authority_scope_provider
        client_runtime = compose_client_runtime(
            cloud_bundle.dsn,
            deployment_namespace=active_namespace or "",
            enabled=settings.client_integration_enabled,
        )
    else:
        from agent_storage import sqlite_control_plane_stores

        active_stores = stores or sqlite_control_plane_stores(database_path)
        cloud_memory_store = None
        active_transaction = worker_projection_transaction
        active_namespace = deployment_namespace
        active_dispatch = effect_dispatch
        active_artifact_factory = None
        active_workspace_resolver_factory = None
        active_provider_factory = cloud_provider_continuation_factory
        active_authority_resolver = None
        active_authority_scope_provider = None
        active_extension_store = None
        active_extension_skills = None
    active_stores, active_transaction = configure_live_event_delivery(
        active_stores,
        active_transaction,
        settings,
    )
    execution_stores = active_stores
    model_call_indexer = ModelCallIndexer(execution_stores.model_calls)
    tool_run_indexer = ToolRunIndexer(execution_stores.tool_runs)
    recovery_service = SessionRecoveryService(
        execution_stores.events,
        execution_stores.sessions,
        execution_stores.workspaces,
        worker_projection_transaction=active_transaction,
        deployment_namespace=active_namespace,
        model_call_indexer=(model_call_indexer if active_transaction is not None else None),
        tool_run_indexer=(tool_run_indexer if active_transaction is not None else None),
    )
    claim_service = SessionClaimService(
        execution_stores.leases,
        recovery_service,
    )
    task_binding_loader = None
    egress_registry = None
    delegation_store = None
    if cloud_memory_store is not None and settings.storage_authority == "postgresql":
        from agent_storage.postgres.task_admission import load_task_binding as _load_binding

        binding_dsn = cloud_bundle.dsn or ""
        if binding_dsn:

            def task_binding_loader(session_id: SessionId) -> object:
                assert active_namespace is not None
                return _load_binding(
                    binding_dsn,
                    deployment_namespace=active_namespace,
                    task_id=_task_binding_id(execution_stores.tasks, session_id),
                )

    frozen_manifest_loader = None
    if cloud_memory_store is not None and settings.storage_authority == "postgresql":
        from agent_storage.postgres.host_manifest_freeze import (
            load_frozen_manifest_by_digest as _load_frozen_manifest,
        )

        manifest_dsn = cloud_bundle.dsn or ""
        if manifest_dsn and active_namespace is not None:

            def frozen_manifest_loader(digest: str) -> object:
                assert active_namespace is not None
                return _load_frozen_manifest(
                    manifest_dsn,
                    deployment_namespace=active_namespace,
                    manifest_digest=digest,
                )

    child_wakeup_service = None
    if cloud_memory_store is not None and settings.storage_authority == "postgresql":
        from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService as _Wakeup

        wakeup_dsn = cloud_bundle.dsn or ""
        if wakeup_dsn and active_namespace is not None:
            child_wakeup_service = _Wakeup(wakeup_dsn, deployment_namespace=active_namespace)
            from agent_storage.postgres.host_connectors import (
                PostgresHostConnectorRegistry,
            )

            egress_registry = PostgresHostConnectorRegistry(
                wakeup_dsn, deployment_namespace=active_namespace
            )
            from agent_storage.postgres.subagent_delegation import (
                PostgresSubagentDelegationStore,
            )

            delegation_store = PostgresSubagentDelegationStore(
                wakeup_dsn, deployment_namespace=active_namespace
            )

    active_extension_mcp = compose_worker_mcp(
        settings, cloud_bundle if settings.storage_authority == "postgresql" else None,
    )
    execution_service = SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=settings,
        stores=execution_stores,
        effect_dispatch=active_dispatch,
        worker_projection_transaction=active_transaction,
        deployment_namespace=active_namespace,
        task_binding_loader=task_binding_loader,
        egress_registry=egress_registry,
        delegation_store=delegation_store,
        frozen_manifest_loader=frozen_manifest_loader,
        client_runtime=client_runtime,
        model_http_client=model_http_client,
        runtime_instance_factory=(
            cloud_bundle.runtime_instance_factory
            if settings.storage_authority == "postgresql"
            else None
        ),
        extension_snapshot_store=active_extension_store,
        extension_skills=active_extension_skills,
        extension_mcp=active_extension_mcp,
        cloud_artifact_factory=active_artifact_factory,
        cloud_provider_continuation_factory=active_provider_factory,
        workspace_resolver=(
            active_workspace_resolver_factory()
            if active_workspace_resolver_factory is not None
            else None
        ),
        execution_authority_resolver=active_authority_resolver,
        execution_authority_scope_provider=active_authority_scope_provider,
    )
    migrated = False
    cutover_probe = None
    if settings.storage_authority == "postgresql":
        from functools import partial

        from zebra_agent_worker.command_process_state import command_cutover_state

        if cloud_bundle.dsn:
            cutover_probe = partial(command_cutover_state, cloud_bundle.dsn, active_namespace or "")
            migrated = command_cutover_state(
                cloud_bundle.dsn,
                active_namespace or "",
                require_ready=(
                    settings.command_delivery.publish_enabled
                    or settings.command_delivery.consume_enabled
                ),
            )
        else:
            raise ValueError("command delivery requires an explicit cloud DSN")
    elif settings.command_delivery.publish_enabled or settings.command_delivery.consume_enabled:
        raise ValueError("Rabbit command delivery requires PostgreSQL cloud composition")
    command_consumer = (
        None
        if migrated
        else SessionCommandConsumer(
            execution_stores,
            execution_service,
            control_service=SessionControlService(
                database_path,
                settings=settings,
                stores=execution_stores,
            ),
        )
    )
    cloud_memory_recovery = None
    if cloud_memory_store is not None:
        assert active_namespace is not None
        assert active_transaction is not None
        cloud_memory_recovery = CloudMemoryFinalizationRecovery(
            claim_service=claim_service,
            recorder_factory=WorkerProjectionRecorderFactory(
                stores=execution_stores,
                model_call_indexer=model_call_indexer,
                tool_run_indexer=tool_run_indexer,
                transaction=active_transaction,
                deployment_namespace=active_namespace,
            ),
            memory_store=cloud_memory_store,
            idempotency_store=execution_stores.idempotency,
            deployment_namespace=active_namespace,
            event_store=execution_stores.events,
            projection_store=execution_stores.sessions,
            workspace_store=execution_stores.workspaces,
            title_service_factory=lambda: SessionTitleService(
                build_model_gateway(model_provider_settings(settings), client=model_http_client)
                if model_http_client is not None
                else build_model_gateway(model_provider_settings(settings))
            ),
        )
    service = WorkerLoopService(
        projection_store=execution_stores.sessions,
        execution_service=execution_service,
        cloud_memory_recovery=cloud_memory_recovery,
        child_wakeup_service=child_wakeup_service,
        sleep=sleep,
        command_consumer=command_consumer,
        scan_ready_sessions=not migrated and settings.deployment != "cloud",
        cutover_probe=None if migrated else cutover_probe,
    )
    if migrated:
        from zebra_agent_worker.command_process import CommandWorkerProcess

        assert cloud_bundle.dsn is not None and active_namespace is not None
        service.migrated_run = CommandWorkerProcess(
            dsn=cloud_bundle.dsn,
            namespace=active_namespace,
            settings=settings,
            execute=execution_service.execute_claimed_session,
            maintenance=service.maintenance_once,
            drain=service.drain,
        ).run
    return service
