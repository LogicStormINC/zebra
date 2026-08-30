from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import agent_core.harness as core_harness
import httpx
import zebra_agent_config
from agent_context import LocalContextCompiler
from agent_core.application import SessionTitleService
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_integrations import build_model_gateway
from agent_runtime.workspace_runtime_resolver import WorkspaceRuntimeResolver
from agent_security import LocalPolicyEngine, PolicyProfile, resolve_effective_network_profile
from agent_storage import ControlPlaneStores, PostgresControlPlaneStores

import zebra_agent_worker.authority_types as authority_types
import zebra_agent_worker.execution_continuations as execution_continuations
import zebra_agent_worker.execution_finalization as execution_finalization
import zebra_agent_worker.provider_continuation_execution as provider_runtime
import zebra_agent_worker.runtime_authority as runtime_authority
import zebra_agent_worker.runtime_setup as runtime_setup
import zebra_agent_worker.session_handoff as handoff
import zebra_agent_worker.tool_output_artifact_runtime as artifact_runtime
from zebra_agent_worker.claims import ClaimedSession, SessionClaimService
from zebra_agent_worker.client_effect_resume import recover_client_effect_wakeup
from zebra_agent_worker.context_materialization import prepare_worker_context
from zebra_agent_worker.continuation_dispatch import run_continuation
from zebra_agent_worker.control import SessionControlService
from zebra_agent_worker.effect_runtime import guard_worker_effects
from zebra_agent_worker.execution_completion import finish_execution
from zebra_agent_worker.execution_context import (
    build_worker_orchestrator,
    harness_task_for_recovered,
)
from zebra_agent_worker.execution_errors import (
    error_metadata,
    exception_attempt_result,
    sequence_race_guard,
)
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder, ExecutionInterrupted
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.execution_preflight import (
    _superseded_by_control_event,
    prepare_execution_preflight,
)
from zebra_agent_worker.execution_recovery import (
    execute_session_with_lease,
    persist_runtime_cleanup_failure,
    recover_execution_inputs,
)
from zebra_agent_worker.execution_storage import resolve_execution_storage
from zebra_agent_worker.gateway_release import GatewayRelease
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.provider_configuration import model_provider_settings
from zebra_agent_worker.provider_continuation_execution import CloudProviderContinuationFactory
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.task_recovery import apply_bound_host_context
from zebra_agent_worker.tool_gateway_runtime import build_worker_tool_gateway
from zebra_agent_worker.tool_run_index import ToolRunIndexer
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory


class SessionExecutionService:
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
        client_runtime: Callable[[SessionId], object] | None = None,
        model_http_client: httpx.Client | None = None,
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
        self._database_path = database_path
        self._client_runtime = client_runtime
        self._model_http_client = model_http_client
        self._claim_service = claim_service
        self._resume_service = resume_service
        self._settings = settings or zebra_agent_config.load_settings()
        storage = resolve_execution_storage(database_path, stores)
        active_stores = storage.stores
        self._task_index_store = getattr(active_stores, "tasks", None)
        self._event_store = active_stores.events
        self._projection_store = active_stores.sessions
        self._workspace_store = active_stores.workspaces
        self._artifact_payload_store = storage.artifact_payload_store
        self._artifact_payload_reader = storage.artifact_payload_reader
        self._provider_continuation_store = storage.provider_continuation_store
        self._memory_store = storage.memory_store
        self._cloud_memory_store = storage.cloud_memory_store
        self._memory_extraction_service = storage.memory_extraction_service
        self._memory_promotion_service = storage.memory_promotion_service
        self._effect_ledger = storage.effect_ledger
        self._deployment_namespace = storage.deployment_namespace
        self._context_lifecycle_store = active_stores.context_lifecycle
        self._context_materialization_store = (
            active_stores.context_materialization
            if isinstance(active_stores, PostgresControlPlaneStores)
            else None
        )
        self._model_call_indexer = ModelCallIndexer(active_stores.model_calls)
        self._tool_run_indexer = ToolRunIndexer(
            active_stores.tool_runs, self._artifact_payload_store
        )
        self._recovery_service = SessionRecoveryService(
            self._event_store,
            self._projection_store,
            self._workspace_store,
            worker_projection_transaction=worker_projection_transaction,
            deployment_namespace=deployment_namespace,
            model_call_indexer=self._model_call_indexer if worker_projection_transaction else None,
            tool_run_indexer=self._tool_run_indexer if worker_projection_transaction else None,
        )
        self._control_service = SessionControlService(
            database_path,
            settings=self._settings,
            stores=active_stores,
        )
        self._projection_recorder_factory = WorkerProjectionRecorderFactory(
            stores=active_stores,
            model_call_indexer=self._model_call_indexer,
            tool_run_indexer=self._tool_run_indexer,
            transaction=worker_projection_transaction,
            deployment_namespace=deployment_namespace,
        )
        self._effect_dispatch = effect_dispatch
        self._workspace_resolver = workspace_resolver
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
        self._egress_registry = egress_registry
        self._delegation_store = delegation_store
        self._frozen_manifest_loader = frozen_manifest_loader

    def execute_session(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        executed_at: datetime | None = None,
        lease_ttl_seconds: int = 30,
    ) -> execution_finalization.ExecutedSession:
        return execute_session_with_lease(
            self,
            session_id,
            worker_id=worker_id,
            executed_at=executed_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def _execute_claimed_session_once(
        self,
        claimed: ClaimedSession,
        *,
        started_at: datetime,
        ownership_check: Callable[[], None],
    ) -> execution_finalization.ExecutedSession:
        session_id = claimed.lease.session_id
        cloud_artifacts = provider_runtime.artifact_for(self._cloud_artifact_factory, session_id)
        with sequence_race_guard("execution inputs lost a sequence race"):
            inputs = recover_execution_inputs(
                claimed=claimed,
                session_id=session_id,
                started_at=started_at,
                cloud_deployment=self._settings.deployment == "cloud",
                cloud_provider_continuation_factory=(self._cloud_provider_continuation_factory),
                provider_continuation_store=self._provider_continuation_store,
                control_service=self._control_service,
                recovery_service=self._recovery_service,
                event_store=self._event_store,
                context_lifecycle_store=self._context_lifecycle_store,
                handoff_gate=self._handoff_gate,
                artifact_payload_reader=self._artifact_payload_reader,
                workspace_resolver=self._workspace_resolver,
            )
        claimed = inputs.claimed
        session_events = inputs.session_events
        provider_continuation = inputs.provider_continuation
        cloud_continuation = inputs.cloud_continuation
        task, recovered_handoff = inputs.task, inputs.recovered_handoff
        active_capsule = inputs.active_capsule
        trusted_local = zebra_agent_config.trusted_local_mode_enabled(self._settings)
        policy_trusted = zebra_agent_config.unrestricted_policy_mode_enabled(self._settings)
        effective_network_profile = resolve_effective_network_profile(
            task.network_profile,
            trusted_local=trusted_local,
        )
        authority_recorder, preflight_failure = prepare_execution_preflight(
            recorder_factory=self._projection_recorder_factory,
            claimed=claimed,
            ownership_check=ownership_check,
            network_profile=effective_network_profile.name.value,
            has_local_artifact_store=self._artifact_payload_store is not None,
            attempt_number=1,
            started_at=started_at,
            events=session_events,
            event_store=self._event_store,
        )
        if preflight_failure is not None:
            return preflight_failure
        provider_settings = model_provider_settings(self._settings)
        model_gateway = (
            build_model_gateway(provider_settings, client=self._model_http_client)
            if self._model_http_client is not None
            else build_model_gateway(provider_settings)
        )
        runtime_handle = None
        runtime = None
        effect_recorder: list[DurableHarnessEventRecorder] = []
        try:
            prepared_context = prepare_worker_context(
                store=self._context_materialization_store,
                task_binding_loader=self._task_binding_loader,
                resolver=self._execution_authority_resolver,
                static_scope=self._execution_authority_scope,
                scope_provider=self._execution_authority_scope_provider,
                recovery_service=self._recovery_service,
                event_store=self._event_store,
                recorder=authority_recorder,
                claimed=claimed,
                events=session_events,
                task=task,
                active_capsule_id=(active_capsule.capsule_id if active_capsule else None),
                as_of=started_at,
            )
            claimed, session_events = prepared_context.claimed, prepared_context.events
            task_binding = prepared_context.binding
            task = apply_bound_host_context(task, task_binding)
            materialized_context = prepared_context.materialization
        except ExecutionInterrupted:
            return _superseded_by_control_event(authority_recorder)
        except (RuntimeError, ValueError) as exc:
            raise WorkerExecutionError(str(exc)) from exc
        try:
            runtime, prepared_runtime = runtime_setup.build_prepared_runtime(
                self._settings,
                self._database_path,
                workspace_root=task.workspace_root,
                network_profile=effective_network_profile.name.value,
                session_id=session_id,
                attempt_number=1,
                artifact_store=self._artifact_payload_store,
                created_at=started_at,
            )
            runtime_handle = prepared_runtime.handle
            authority = runtime_handle.authority
            runtime_setup.require_matching_runtime_authority(
                runtime_handle,
                None if trusted_local else claimed.recovery.workspace.runtime_spec_digest,
            )
            authority_recorder = self._projection_recorder_factory.build(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                lease=claimed.lease,
                ownership_check=ownership_check,
            )
            if runtime_authority.persist_runtime_authority(
                authority_recorder, authority, created_at=started_at
            ):
                claimed = ClaimedSession(
                    recovery=self._recovery_service.recover_session(
                        session_id,
                        worker_lease=claimed.lease,
                    ),
                    lease=claimed.lease,
                )
            local_tool_gateway = build_worker_tool_gateway(
                task,
                settings=self._settings,
                model_gateway=model_gateway,
                session_history=self._session_history,
                session_id=session_id,
                runtime=runtime,
                runtime_handle=runtime_handle,
                local_artifacts=self._artifact_payload_store,
                cloud_artifacts=cloud_artifacts,
                trusted_local=trusted_local,
                egress_registry=self._egress_registry,
                delegation_store=self._delegation_store,
                parent_task_id=session_id,
                durable_delegation=self._settings.deployment == "cloud",
                parent_binding_digest=(task_binding.binding_digest if task_binding else None),
                parent_binding=task_binding,
                parent_context=materialized_context,
                manifest_digest=(
                    task_binding.host_capability.manifest_digest if task_binding else None
                ),
                frozen_manifest_loader=self._frozen_manifest_loader,
                client_gateway=self._client_runtime(session_id) if self._client_runtime else None,  # type: ignore[arg-type]
            )
            tool_gateway = guard_worker_effects(
                local_tool_gateway,
                ledger=self._effect_ledger,
                session_id=session_id,
                recovered_handoff=recovered_handoff,
                authority_scope=(
                    f"{task.workspace_root.resolve()}|{task.policy_profile}|"
                    f"{effective_network_profile.name.value}"
                ),
                dispatch=self._effect_dispatch,
                local_artifacts=self._artifact_payload_store,
                lease=claimed.lease,
                recorders=effect_recorder,
                ownership_check=ownership_check,
                cloud_artifacts=cloud_artifacts,
            )
        except ExecutionInterrupted:
            cleanup_error = runtime_setup.destroy_runtime(runtime, runtime_handle)
            if cleanup_error is not None:
                persist_runtime_cleanup_failure(
                    recorder=authority_recorder,
                    error=cleanup_error,
                    target="runtime",
                    created_at=started_at,
                )
            return _superseded_by_control_event(authority_recorder)
        except Exception as exc:
            if runtime is None:
                cleanup_error = None
            else:
                cleanup_error = runtime_setup.destroy_runtime(runtime, runtime_handle)
            if cleanup_error is not None:
                persist_runtime_cleanup_failure(
                    recorder=authority_recorder,
                    error=cleanup_error,
                    target="runtime",
                    created_at=started_at,
                )
                raise WorkerExecutionError(
                    f"{exc}; runtime cleanup failed: {cleanup_error}"
                ) from cleanup_error
            raise WorkerExecutionError(str(exc)) from exc
        release_gateway = GatewayRelease(tool_gateway, authority_recorder, started_at=started_at)

        try:
            context_compiler = LocalContextCompiler(include_workspace=task_binding is None)
            context = core_harness.HarnessContext(
                task=harness_task_for_recovered(
                    task,
                    network_profile=effective_network_profile,
                    tool_gateway=tool_gateway,
                    memory_store=self._memory_store,
                    materialization=materialized_context,
                ),
                session=claimed.recovery.session,
                attempt=core_harness.HarnessAttempt(number=1, started_at=started_at),
            )
            with sequence_race_guard("continuation start lost a sequence race"):
                claimed, continuations = execution_continuations.recover_and_start_continuations(
                    claimed,
                    session_events=session_events,
                    event_store=self._event_store,
                    recovery_service=self._recovery_service,
                    started_at=started_at,
                    recorder=authority_recorder,
                    cleanup=release_gateway,
                    child_result_verifier=execution_continuations.build_child_result_verifier(
                        self._delegation_store, self._projection_store
                    ),
                )
            continuation = continuations.approved
            clarification = continuations.clarification
            child_wakeup = continuations.child_wakeup
            context = core_harness.HarnessContext(
                task=context.task,
                session=claimed.recovery.session,
                attempt=context.attempt,
            )
            recorder = self._projection_recorder_factory.build(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                lease=claimed.lease,
                ownership_check=ownership_check,
            )
            release_gateway.recorder = recorder
            effect_recorder.append(recorder)
            if continuation is None and clarification is None and child_wakeup is None:
                recorder.append(
                    EventType.HARNESS_ATTEMPT_STARTED,
                    EventActor.HARNESS,
                    {"attempt_number": 1},
                    created_at=started_at,
                )
            context = core_harness.HarnessContext(
                task=context.task,
                session=recorder.session,
                attempt=context.attempt,
            )
            orchestrator = build_worker_orchestrator(
                model_gateway=model_gateway,
                tool_gateway=tool_gateway,
                policy_engine=LocalPolicyEngine(
                    profile=PolicyProfile(task.policy_profile),
                    network_profile=effective_network_profile,
                    web_search_endpoint=self._settings.web_search_endpoint,
                    trusted_local=policy_trusted,
                    additional_read_only_tools=tool_gateway.read_only_tools,
                    additional_approval_tools=local_tool_gateway.approval_tools,
                ),
                context_compiler=context_compiler,
                cloud_continuation=cloud_continuation,
                recorder=recorder,
                event_store=self._event_store,
                lifecycle_store=self._context_lifecycle_store,
                cloud_artifacts=cloud_artifacts,
                local_continuation_store=self._provider_continuation_store,
                session_id=session_id,
                provider_continuation=provider_continuation,
            )
            client_wakeup = recover_client_effect_wakeup(session_events)
            try:
                attempt_result = run_continuation(
                    orchestrator,
                    context,
                    continuation=continuation,
                    clarification=clarification,
                    child_wakeup=child_wakeup,
                    client_effect=client_wakeup,
                )
            except Exception as exc:
                attempt_result = exception_attempt_result(
                    exc, error_metadata(exc, clarification, continuation)
                )
            finally:
                cleanup_error = release_gateway()
            if cleanup_error is not None:
                attempt_result = runtime_authority.runtime_cleanup_failure_result(
                    cleanup_error, attempt_result
                )
            return finish_execution(
                recorder=recorder,
                attempt_result=attempt_result,
                memory_extraction_service=self._memory_extraction_service,
                memory_promotion_service=self._memory_promotion_service,
                title_service=SessionTitleService(model_gateway),
                event_store=self._event_store,
                cloud_memory_store=self._cloud_memory_store,
                deployment_namespace=self._deployment_namespace,
                projection_store=self._projection_store,
                workspace_store=self._workspace_store,
                task_index_store=self._task_index_store,
                session_id=session_id,
                started_at=started_at,
                interaction_mode=task.interaction_mode,
            )
        except ExecutionInterrupted:
            release_gateway()
            return _superseded_by_control_event(release_gateway.recorder)
        except BaseException as exc:
            if (cleanup_error := release_gateway()) is not None:
                exc.add_note(f"tool gateway cleanup failed: {type(cleanup_error).__name__}")
            raise
