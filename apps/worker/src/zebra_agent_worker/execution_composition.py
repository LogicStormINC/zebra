"""Dependency wiring for SessionExecutionService; execution stays in its own module."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import zebra_agent_config
from agent_core.domain.identifiers import SessionId
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_runtime.workspace_runtime_resolver import WorkspaceRuntimeResolver
from agent_storage import ControlPlaneStores, PostgresControlPlaneStores

import zebra_agent_worker.authority_types as authority_types
import zebra_agent_worker.execution_tool_gateway as execution_gateway
import zebra_agent_worker.provider_continuation_execution as provider_runtime
import zebra_agent_worker.runtime_authority as runtime_authority
import zebra_agent_worker.runtime_setup as runtime_setup
import zebra_agent_worker.session_handoff as handoff
import zebra_agent_worker.tool_output_artifact_runtime as artifact_runtime
from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.client_tool_gateway import ClientToolGateway
from zebra_agent_worker.control import SessionControlService
from zebra_agent_worker.coverage_composition import CloudCoverageRuntime
from zebra_agent_worker.execution_finalization import (
    RetryableWorkerSetupError as RetryableWorkerSetupError,
)
from zebra_agent_worker.execution_storage import compose_recovery, resolve_execution_storage
from zebra_agent_worker.extension_recovery import WorkerExtensionStore
from zebra_agent_worker.provider_continuation_execution import CloudProviderContinuationFactory
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.transient_output_runtime import TransientOutputFactory
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory


class SessionExecutionComposition:
    def __init__(
        self,
        *,
        database_path: Path,
        claim_service: SessionClaimService,
        resume_service: SessionResumeService,
        settings: zebra_agent_config.ZebraAgentSettings | None = None,
        stores: ControlPlaneStores | PostgresControlPlaneStores | None = None,
        effect_dispatch: EffectDispatchPort | None = None,
        workspace_resolver: WorkspaceRuntimeResolver | None = None,
        worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
        deployment_namespace: str | None = None,
        cloud_artifact_factory: artifact_runtime.CloudArtifactCoordinatorFactory | None = None,
        cloud_provider_continuation_factory: CloudProviderContinuationFactory | None = None,
        execution_authority_resolver: authority_types.AuthorityResolver | None = None,
        execution_authority_scope: authority_types.AuthorityScope | None = None,
        execution_authority_scope_provider: authority_types.AuthorityScopeProvider | None = None,
        task_binding_loader: Callable[[SessionId], object] | None = None,
        egress_registry: HostConnectorRegistryPort | None = None,
        delegation_store: object | None = None,
        frozen_manifest_loader: Callable[[str], object] | None = None,
        client_runtime: Callable[[SessionId], ClientToolGateway | None] | None = None,
        model_http_client: httpx.Client | None = None,
        runtime_instance_factory: runtime_setup.InstanceFactory | None = None,
        extension_snapshot_store: WorkerExtensionStore | None = None,
        extension_skills: execution_gateway.WorkerSkillSource | None = None,
        extension_mcp: execution_gateway.WorkerMcpSource | None = None,
        extension_plugins: execution_gateway.WorkerPluginSource | None = None,
        recorder_factory: WorkerProjectionRecorderFactory | None = None,
        coverage_runtime: CloudCoverageRuntime | None = None,
        transient_output_factory: TransientOutputFactory | None = None,
    ) -> None:
        runtime_authority.validate_authority_wiring(
            execution_authority_resolver,
            execution_authority_scope,
            execution_authority_scope_provider,
        )
        cloud_artifact_factory = artifact_runtime.validate_cloud_artifact_factory(
            cloud_artifact_factory,
            worker_projection_transaction,
            deployment_namespace,
            effect_dispatch,
        )
        provider_runtime.validate_factory(
            cloud_provider_continuation_factory,
            worker_projection_transaction,
            deployment_namespace,
            stores,
        )
        settings = settings or zebra_agent_config.load_settings()
        self._database_path, self._settings = database_path, settings
        self._runtime_instance_factory = runtime_instance_factory
        self._client_runtime, self._model_http_client = client_runtime, model_http_client
        self._claim_service, self._resume_service = claim_service, resume_service
        storage = resolve_execution_storage(database_path, stores)
        active_stores = storage.stores
        self._personalization_store = getattr(active_stores, "personalization", None)
        self._task_index_store = getattr(active_stores, "tasks", None)
        self._event_store, self._projection_store = active_stores.events, active_stores.sessions
        self._workspace_store = active_stores.workspaces
        self._artifact_payload_store, self._artifact_payload_reader = (
            storage.artifact_payload_store,
            storage.artifact_payload_reader,
        )
        self._provider_continuation_store, self._memory_store = (
            storage.provider_continuation_store,
            storage.memory_store,
        )
        self._cloud_memory_store = storage.cloud_memory_store
        self._memory_extraction_service = storage.memory_extraction_service
        self._memory_promotion_service = storage.memory_promotion_service
        self._effect_ledger = storage.effect_ledger
        self._deployment_namespace = storage.deployment_namespace
        self._execution_namespace = deployment_namespace
        self._execution_input_store = getattr(active_stores, "execution_inputs", None)
        self._context_lifecycle_store = active_stores.context_lifecycle
        self._context_materialization_store = (
            active_stores.context_materialization
            if isinstance(active_stores, PostgresControlPlaneStores)
            else None
        )
        self._model_call_indexer, self._tool_run_indexer, self._recovery_service = compose_recovery(
            active_stores,
            worker_projection_transaction,
            deployment_namespace,
            self._artifact_payload_store,
        )
        self._control_service = SessionControlService(
            database_path,
            settings=self._settings,
            stores=active_stores,
        )
        self._projection_recorder_factory = recorder_factory or WorkerProjectionRecorderFactory(
            stores=active_stores,
            model_call_indexer=self._model_call_indexer,
            tool_run_indexer=self._tool_run_indexer,
            transaction=worker_projection_transaction,
            deployment_namespace=deployment_namespace,
        )
        self._effect_dispatch, self._workspace_resolver = effect_dispatch, workspace_resolver
        self._session_history = active_stores.session_history
        self._handoff_gate = handoff.SessionHandoffRecoveryGate(
            str(database_path),
            stores=active_stores,
            worker_projection_transaction=worker_projection_transaction,
            deployment_namespace=deployment_namespace,
        )
        self._cloud_artifact_factory = cloud_artifact_factory
        self._cloud_provider_continuation_factory = cloud_provider_continuation_factory
        self._execution_authority_resolver = execution_authority_resolver
        self._execution_authority_scope = execution_authority_scope
        self._execution_authority_scope_provider = execution_authority_scope_provider
        self._task_binding_loader = task_binding_loader
        self._egress_registry, self._delegation_store = egress_registry, delegation_store
        self._frozen_manifest_loader = frozen_manifest_loader
        self._extensions = execution_gateway.extensions(
            extension_snapshot_store, extension_skills, extension_mcp, extension_plugins
        )
        self._coverage_runtime = coverage_runtime
        self._transient_output_factory = transient_output_factory
