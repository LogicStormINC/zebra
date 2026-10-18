from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import agent_core.harness as core_harness
import httpx
import zebra_agent_config
from agent_context import LocalContextCompiler
from agent_core.application import SessionTitleService
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_integrations import build_model_gateway
from agent_runtime.workspace_runtime_resolver import WorkspaceRuntimeResolver
from agent_security import LocalPolicyEngine, PolicyProfile, resolve_effective_network_profile
from agent_storage import ControlPlaneStores, PostgresControlPlaneStores

import zebra_agent_worker.authority_types as authority_types
import zebra_agent_worker.execution_context as execution_context
import zebra_agent_worker.execution_continuations as execution_continuations
import zebra_agent_worker.execution_preflight as execution_preflight
import zebra_agent_worker.execution_runtime as execution_runtime
import zebra_agent_worker.execution_tool_gateway as execution_gateway
import zebra_agent_worker.provider_continuation_execution as provider_runtime
import zebra_agent_worker.runtime_authority as runtime_authority
import zebra_agent_worker.runtime_setup as runtime_setup
import zebra_agent_worker.session_handoff as handoff
import zebra_agent_worker.tool_output_artifact_runtime as artifact_runtime
from zebra_agent_worker.claims import ClaimedSession, SessionClaimService
from zebra_agent_worker.client_tool_gateway import ClientToolGateway
from zebra_agent_worker.completion_recovery import recover_committed_completion
from zebra_agent_worker.context_materialization import prepare_worker_context
from zebra_agent_worker.control import SessionControlService
from zebra_agent_worker.coverage_composition import CloudCoverageRuntime
from zebra_agent_worker.effect_runtime import guard_worker_effects
from zebra_agent_worker.execution_completion import finish_execution, run_worker_continuation
from zebra_agent_worker.execution_entrypoints import SessionExecutionEntrypoints
from zebra_agent_worker.execution_errors import log_worker_failure, sequence_race_guard
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder, ExecutionInterrupted
from zebra_agent_worker.execution_finalization import ExecutedSession, WorkerExecutionError
from zebra_agent_worker.execution_finalization import (
    RetryableWorkerSetupError as RetryableWorkerSetupError,
)
from zebra_agent_worker.execution_preparation import (
    execution_event_view,
    finish_preparation,
    prepare_execution_inputs,
)
from zebra_agent_worker.execution_recovery import (
    destroy_runtime_with_evidence,
    raise_runtime_setup_failure,
    recover_execution_inputs,
    recover_execution_progress,
)
from zebra_agent_worker.execution_storage import compose_recovery, resolve_execution_storage
from zebra_agent_worker.extension_recovery import WorkerExtensionStore
from zebra_agent_worker.gateway_release import GatewayRelease
from zebra_agent_worker.provider_continuation_execution import CloudProviderContinuationFactory
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.task_recovery import apply_bound_host_context
from zebra_agent_worker.transient_output_runtime import TransientOutputFactory
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory


class SessionExecutionService(SessionExecutionEntrypoints):
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
        recorder_factory: WorkerProjectionRecorderFactory | None = None,
        coverage_runtime: CloudCoverageRuntime | None = None,
        transient_output_factory: TransientOutputFactory | None = None,
    ) -> None:
        runtime_authority.validate_authority_wiring(
            execution_authority_resolver,
            execution_authority_scope, execution_authority_scope_provider,
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
            extension_snapshot_store, extension_skills, extension_mcp
        )
        self._coverage_runtime = coverage_runtime
        self._transient_output_factory = transient_output_factory

    def _execute_claimed_session_once(
        self,
        claimed: ClaimedSession,
        *,
        started_at: datetime,
        ownership_check: Callable[[], None],
    ) -> ExecutedSession:
        session_id = claimed.lease.session_id
        if (completed := recover_committed_completion(self, claimed, ownership_check, started_at)):
            return completed
        worker_progress = finish_preparation(
            lambda: recover_execution_progress(self, claimed, ownership_check), ownership_check
        )
        attempt_number = worker_progress.head.state.attempt_number if worker_progress else 1
        cloud_artifacts = provider_runtime.artifact_for(self._cloud_artifact_factory, session_id)
        with sequence_race_guard("execution inputs lost a sequence race"):
            inputs = prepare_execution_inputs(
                self,
                claimed,
                started_at,
                ownership_check,
                lambda **kwargs: recover_execution_inputs(
                    **kwargs, strict_dispatch_configured=self._coverage_runtime is not None
                ),
            )
        claimed = inputs.claimed
        session_events = inputs.session_events
        provider_continuation = inputs.provider_continuation
        cloud_continuation = inputs.cloud_continuation
        task, recovered_handoff = inputs.task, inputs.recovered_handoff
        active_capsule, runtime_handle, runtime = inputs.active_capsule, None, None
        execution_events = execution_event_view(
            self._event_store,
            inputs.execution_input_reader,
            claimed.lease,
            ownership_check,
            admitted_events=session_events,
        )
        trusted_local = zebra_agent_config.trusted_local_mode_enabled(self._settings)
        policy_trusted = zebra_agent_config.unrestricted_policy_mode_enabled(self._settings)
        effective_network_profile = resolve_effective_network_profile(
            task.network_profile,
            trusted_local=trusted_local,
        )
        authority_recorder, preflight_failure = execution_preflight.prepare_execution_preflight(
            recorder_factory=self._projection_recorder_factory,
            claimed=claimed,
            ownership_check=ownership_check,
            network_profile=effective_network_profile.name.value,
            has_local_artifact_store=self._artifact_payload_store is not None,
            attempt_number=attempt_number,
            started_at=started_at,
            events=session_events,
            event_store=execution_events,
        )
        if preflight_failure is not None:
            return preflight_failure
        if task.coverage_admission is not None:
            if self._coverage_runtime is None:
                raise WorkerExecutionError("coverage_unsupported")
            return self._coverage_runtime.execute(self, inputs, authority_recorder, ownership_check)
        model_gateway = execution_gateway.model_gateway(self, build_model_gateway)
        effect_recorder: list[DurableHarnessEventRecorder] = []
        try:
            prepared_context = prepare_worker_context(
                store=self._context_materialization_store,
                task_binding_loader=self._task_binding_loader,
                resolver=self._execution_authority_resolver,
                static_scope=self._execution_authority_scope,
                scope_provider=self._execution_authority_scope_provider,
                recovery_service=self._recovery_service,
                event_store=execution_events,
                recorder=authority_recorder,
                claimed=claimed,
                events=session_events,
                task=task,
                active_capsule_id=(active_capsule.capsule_id if active_capsule else None),
                as_of=started_at,
                extension_store=self._extensions.snapshot_store,
                allow_mcp=self._extensions.mcp is not None,
                attempt_number=attempt_number,
                execution_input_reader=inputs.execution_input_reader,
                ownership_check=ownership_check,
            )
            claimed, session_events = prepared_context.claimed, prepared_context.events
            task_binding = prepared_context.binding
            task = apply_bound_host_context(task, task_binding)
            materialized_context = prepared_context.materialization
        except ExecutionInterrupted:
            return execution_preflight._superseded_by_control_event(authority_recorder)
        except (RuntimeError, ValueError) as exc:
            log_worker_failure("worker_setup_failed", "context_prepare", session_id, exc)
            raise WorkerExecutionError(str(exc)) from exc
        setup_stage = "runtime_instance_binding"
        try:
            compatible_ids = runtime_setup.runtime_session_ids(self._task_index_store, session_id)
            bound_instance_factory = runtime_setup.bind_instance_factory(
                self._runtime_instance_factory, claimed.lease, session_events, task_binding
            )
            setup_stage = "runtime_provision"
            authority_recorder = self._projection_recorder_factory.build(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                lease=claimed.lease,
                ownership_check=ownership_check,
            )
            runtime_preparation = execution_runtime.compose_execution_runtime(
                self._settings, self._database_path,
                claimed=claimed, task=task, binding=task_binding,
                materialization=materialized_context,
                network_profile=effective_network_profile.name.value,
                has_capsule=active_capsule is not None, attempt_number=attempt_number,
                created_at=started_at, artifact_store=self._artifact_payload_store,
                instance_factory=bound_instance_factory, compatible_session_ids=compatible_ids,
                recorder=lambda: effect_recorder[-1] if effect_recorder else authority_recorder,
                trusted_local=trusted_local,
            )
            runtime, runtime_handle, authority_persisted = runtime_preparation
            if authority_persisted:
                claimed = ClaimedSession(
                    recovery=self._recovery_service.recover_session(
                        session_id, worker_lease=claimed.lease,
                    ),
                    lease=claimed.lease,
                )
            setup_stage = "tool_gateway"
            local_tool_gateway = execution_gateway.build_execution_tool_gateway(
                self,
                task=task,
                model_gateway=model_gateway,
                session_id=session_id,
                runtime=runtime,
                runtime_handle=runtime_handle,
                cloud_artifacts=cloud_artifacts,
                trusted_local=trusted_local,
                task_binding=task_binding,
                materialized_context=materialized_context,
                extension=prepared_context.extension,
                fence=claimed.lease.fence,
                attempt_number=attempt_number,
                network_cancellation_check=authority_recorder.require_active_execution,
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
        except ExecutionInterrupted as interruption:
            destroy_runtime_with_evidence(
                runtime,
                runtime_handle,
                recorder=authority_recorder,
                created_at=started_at,
                attempt_number=attempt_number,
            )
            return execution_preflight._superseded_by_control_event(
                authority_recorder, interruption
            )
        except Exception as exc:
            raise_runtime_setup_failure(
                exc,
                runtime,
                runtime_handle,
                recorder=authority_recorder,
                stage=setup_stage,
                created_at=started_at,
                attempt_number=attempt_number,
            )
        release_gateway = GatewayRelease(
            tool_gateway, authority_recorder, started_at=started_at, attempt_number=attempt_number
        )
        try:
            context_compiler = LocalContextCompiler(include_workspace=task_binding is None)
            context = core_harness.HarnessContext(
                task=execution_context.harness_task_for_recovered(
                    task,
                    network_profile=effective_network_profile,
                    tool_gateway=tool_gateway,
                    memory_store=self._memory_store,
                    personalization_store=self._personalization_store,
                    materialization=materialized_context,
                ),
                session=claimed.recovery.session,
                attempt=core_harness.HarnessAttempt(number=attempt_number, started_at=started_at),
            )
            setup_stage = "continuation_recovery"
            with sequence_race_guard("continuation start lost a sequence race"):
                claimed, continuations = execution_continuations.recover_and_start_continuations(
                    claimed,
                    session_events=session_events,
                    event_store=execution_events,
                    recovery_service=self._recovery_service,
                    started_at=started_at,
                    recorder=authority_recorder,
                    cleanup=release_gateway,
                    child_result_verifier=execution_continuations.build_child_result_verifier(
                        self._delegation_store, self._projection_store
                    ),
                    attempt_number=attempt_number,
                )
            continuation = continuations.approved
            clarification = continuations.clarification
            child_wakeup = continuations.child_wakeup
            client_wakeup = continuations.client_effect
            setup_stage = "continuation_recorder"
            recorder = self._projection_recorder_factory.build(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                lease=claimed.lease,
                ownership_check=ownership_check,
            )
            release_gateway.recorder = recorder
            effect_recorder.append(recorder)
            if not any((continuation, clarification, child_wakeup, client_wakeup)) and (
                worker_progress is None
                or not worker_progress.head.state.attempt_started
                or recorder.session.status is SessionStatus.READY
            ):
                recorder.append(
                    EventType.HARNESS_ATTEMPT_STARTED,
                    EventActor.HARNESS,
                    {"attempt_number": attempt_number},
                    created_at=started_at,
                )
            context = replace(context, session=recorder.session)
            setup_stage = "orchestrator_build"
            orchestrator = execution_context.build_worker_orchestrator(
                model_gateway=model_gateway,
                tool_gateway=tool_gateway,
                policy_engine=LocalPolicyEngine(
                    profile=PolicyProfile(task.policy_profile),
                    network_profile=effective_network_profile,
                    web_search_endpoint=self._settings.web_search_endpoint,
                    web_pipeline_v2=self._settings.web_pipeline_v2,
                    trusted_local=policy_trusted,
                    additional_read_only_tools=local_tool_gateway.read_only_tools,
                    additional_write_tools=local_tool_gateway.authorized_write_tools,
                    additional_approval_tools=local_tool_gateway.approval_required_tools,
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
                invocation_policy=task.model_invocation_policy,
                public_output_policy=self._settings.public_output,
                worker_progress=worker_progress,
                transient_output=(self._transient_output_factory(worker_progress, claimed.lease)
                    if self._transient_output_factory and worker_progress else None),
                user_input=task.user_input,
                attempt_number=attempt_number,
            )
            setup_stage = "continuation_run"
            attempt_result = run_worker_continuation(
                orchestrator,
                context,
                continuation=continuation,
                clarification=clarification,
                child_wakeup=child_wakeup,
                client_effect=client_wakeup,
                release_gateway=release_gateway,
            )
            return finish_execution(
                recorder=recorder,
                attempt_result=attempt_result,
                memory_extraction_service=self._memory_extraction_service,
                memory_promotion_service=self._memory_promotion_service,
                title_service=SessionTitleService(model_gateway),
                event_store=execution_events,
                cloud_memory_store=self._cloud_memory_store,
                deployment_namespace=self._deployment_namespace,
                projection_store=self._projection_store,
                workspace_store=self._workspace_store,
                task_index_store=self._task_index_store,
                session_id=session_id,
                started_at=started_at,
                interaction_mode=task.interaction_mode,
                attempt_number=attempt_number,
            )
        except ExecutionInterrupted as interruption:
            release_gateway()
            return execution_preflight._superseded_by_control_event(
                release_gateway.recorder, interruption
            )
        except BaseException as exc:
            log_worker_failure("worker_execution_failed", setup_stage, session_id, exc)
            if (cleanup_error := release_gateway()) is not None:
                exc.add_note(f"tool gateway cleanup failed: {type(cleanup_error).__name__}")
            raise
