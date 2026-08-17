from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.application import SessionTitleService
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_core.harness import (
    HarnessAttempt,
    HarnessContext,
    HarnessModelStep,
    SingleAttemptOrchestrator,
)
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_core.ports.execution_authority import ExecutionAuthorityResolverPort
from agent_integrations import build_model_gateway
from agent_security import LocalPolicyEngine, PolicyProfile, resolve_effective_network_profile
from agent_storage import ControlPlaneStores, PostgresControlPlaneStores
from zebra_agent_config import (
    ZebraAgentSettings,
    load_settings,
    trusted_local_mode_enabled,
)

import zebra_agent_worker.provider_continuation_execution as provider_runtime
import zebra_agent_worker.runtime_setup as runtime_setup
import zebra_agent_worker.session_handoff as handoff
import zebra_agent_worker.tool_output_artifact_runtime as artifact_runtime
from zebra_agent_worker.approved_continuation import (
    ApprovedContinuationError,
    recover_approved_continuation,
)
from zebra_agent_worker.claims import ClaimedSession, SessionClaimService
from zebra_agent_worker.clarification_continuation import (
    ClarificationContinuationError,
    recover_clarification_continuation,
)
from zebra_agent_worker.continuation_lifecycle import (
    mark_approved_continuation_started,
    mark_clarification_continuation_started,
)
from zebra_agent_worker.control import SessionControlError, SessionControlService
from zebra_agent_worker.effect_runtime import guard_worker_effects
from zebra_agent_worker.execution_context import harness_task_for_recovered
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    WorkerExecutionError,
    finalize_execution,
)
from zebra_agent_worker.execution_preflight import prepare_execution_preflight
from zebra_agent_worker.execution_storage import resolve_execution_storage
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.provider_continuation_execution import CloudProviderContinuationFactory
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.runtime_authority import (
    close_tool_gateway,
    persist_attempt_authority,
    persist_runtime_authority,
    runtime_cleanup_failure_result,
)
from zebra_agent_worker.task_recovery import recover_task
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
        settings: ZebraAgentSettings | None = None,
        stores: ControlPlaneStores | PostgresControlPlaneStores | None = None,
        effect_dispatch: EffectDispatchPort | None = None,
        worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
        deployment_namespace: str | None = None,
        cloud_artifact_factory: artifact_runtime.CloudArtifactCoordinatorFactory | None = None,
        cloud_provider_continuation_factory: CloudProviderContinuationFactory | None = None,
        execution_authority_resolver: ExecutionAuthorityResolverPort | None = None,
        execution_authority_scope: OpaqueAuthorityScope | None = None,
    ) -> None:
        if execution_authority_resolver is not None and execution_authority_scope is None:
            raise ValueError("execution_authority_scope is required for an authority resolver")
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
        self._claim_service = claim_service
        self._resume_service = resume_service
        self._settings = settings or load_settings()
        storage = resolve_execution_storage(database_path, stores)
        active_stores = storage.stores
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
            model_call_indexer=(
                self._model_call_indexer if worker_projection_transaction is not None else None
            ),
            tool_run_indexer=(
                self._tool_run_indexer if worker_projection_transaction is not None else None
            ),
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

    def execute_session(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        executed_at: datetime | None = None,
        lease_ttl_seconds: int = 30,
    ) -> ExecutedSession:
        started_at = executed_at or datetime.now(UTC)
        claimed = self._claim_service.claim_session(
            session_id,
            worker_id=worker_id,
            claimed_at=started_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        with LeaseHeartbeat(
            self._claim_service,
            claimed.lease,
            lease_ttl_seconds=lease_ttl_seconds,
        ) as heartbeat:
            resumed = self._resume_service.require_resumable(
                claimed,
                release_on_failure=False,
            )
            heartbeat.require_owned()
            return self._execute_claimed_session(
                resumed.claimed,
                started_at=started_at,
                ownership_check=heartbeat.require_owned,
            )

    def _execute_claimed_session(
        self,
        claimed: ClaimedSession,
        *,
        started_at: datetime,
        ownership_check: Callable[[], None],
    ) -> ExecutedSession:
        session_id = claimed.lease.session_id
        cloud_artifacts = provider_runtime.artifact_for(self._cloud_artifact_factory, session_id)
        cloud_continuation = provider_runtime.cloud_for_session(
            self._cloud_provider_continuation_factory, session_id
        )
        restored = None
        if claimed.recovery.session.status is SessionStatus.SUSPENDED:
            if self._settings.profile == "cloud":
                raise WorkerExecutionError(
                    "cloud suspended-session restoration is not supported by the default Worker"
                )
            try:
                restored = self._control_service.restore_suspended_workspace(
                    session_id,
                    resumed_at=started_at,
                )
            except SessionControlError as exc:
                raise WorkerExecutionError(str(exc)) from exc
        if restored is not None:
            claimed = ClaimedSession(
                recovery=self._recovery_service.recover_session(
                    session_id,
                    worker_lease=claimed.lease,
                ),
                lease=claimed.lease,
            )
        recovered_handoff = handoff.recover_worker_handoff(
            self._handoff_gate,
            session_id,
            fence=claimed.lease.fence,
            recovered_at=started_at,
            release=lambda: None,
        )
        session_events = self._event_store.list_for_session(session_id)
        active_context = self._context_lifecycle_store.get_active_capsule(session_id)
        provider_continuation = provider_runtime.resolve_provider_continuation(
            cloud_continuation,
            session_events,
            self._provider_continuation_store,
        )
        try:
            task = recover_task(
                session_events,
                workspace=claimed.recovery.workspace,
                fallback_title=claimed.recovery.session.title,
                attachment_reader=self._artifact_payload_reader,
                active_capsule=active_context.capsule if active_context else None,
                handoff_evidence=(
                    None if recovered_handoff is None else recovered_handoff.runtime_evidence
                ),
            )
        except (FileNotFoundError, ValueError) as exc:
            raise WorkerExecutionError(str(exc)) from exc
        trusted_local = trusted_local_mode_enabled(self._settings)
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
        )
        if preflight_failure is not None:
            return preflight_failure
        model_gateway = build_model_gateway(self._settings)
        runtime_handle = None
        effect_recorder: list[DurableHarnessEventRecorder] = []
        try:
            if persist_attempt_authority(
                authority_recorder,
                self._execution_authority_resolver,
                self._execution_authority_scope,
                session_id=session_id,
                existing_events=session_events,
                attempt_number=1,
                created_at=started_at,
            ):
                claimed = ClaimedSession(
                    recovery=self._recovery_service.recover_session(
                        session_id,
                        worker_lease=claimed.lease,
                    ),
                    lease=claimed.lease,
                )
                session_events = self._event_store.list_for_session(session_id)
        except ValueError as exc:
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
            if persist_runtime_authority(authority_recorder, authority, created_at=started_at):
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
        except Exception as exc:
            cleanup_error = None
            if runtime_handle is not None:
                try:
                    runtime.destroy(runtime_handle)
                except Exception as error:
                    cleanup_error = error
            if cleanup_error is not None:
                raise WorkerExecutionError(
                    f"{exc}; runtime cleanup failed: {cleanup_error}"
                ) from cleanup_error
            raise WorkerExecutionError(str(exc)) from exc
        context_compiler = LocalContextCompiler()
        context = HarnessContext(
            task=harness_task_for_recovered(
                task,
                network_profile=effective_network_profile,
                tool_gateway=tool_gateway,
                memory_store=self._memory_store,
            ),
            session=claimed.recovery.session,
            attempt=HarnessAttempt(number=1, started_at=started_at),
        )
        try:
            continuation = recover_approved_continuation(session_events)
            clarification = recover_clarification_continuation(session_events)
            if continuation is not None and clarification is not None:
                raise WorkerExecutionError("session has multiple active continuations")
        except (
            ApprovedContinuationError,
            ClarificationContinuationError,
            WorkerExecutionError,
        ) as exc:
            cleanup_error = close_tool_gateway(tool_gateway)
            if cleanup_error is not None:
                raise WorkerExecutionError(
                    f"{exc}; runtime cleanup failed: {cleanup_error}"
                ) from cleanup_error
            raise WorkerExecutionError(str(exc)) from exc
        if continuation is not None:
            claimed = mark_approved_continuation_started(
                claimed,
                event_store=self._event_store,
                recovery_service=self._recovery_service,
                tool_name=continuation.tool_call.name,
                tool_call_id=str(continuation.tool_call.tool_call_id),
                started_at=started_at,
                recorder=authority_recorder,
            )
        elif clarification is not None:
            claimed = mark_clarification_continuation_started(
                claimed,
                event_store=self._event_store,
                recovery_service=self._recovery_service,
                clarification_id=str(clarification.tool_call.tool_call_id),
                started_at=started_at,
                recorder=authority_recorder,
            )
        context = HarnessContext(
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
        effect_recorder.append(recorder)
        if continuation is None and clarification is None:
            recorder.append(
                EventType.HARNESS_ATTEMPT_STARTED,
                EventActor.HARNESS,
                {"attempt_number": 1},
                created_at=started_at,
            )
        context = HarnessContext(
            task=context.task,
            session=recorder.session,
            attempt=context.attempt,
        )
        persist_event, prepare_continuation = provider_runtime.build_worker_context_sinks(
            cloud_continuation,
            recorder=recorder,
            event_store=self._event_store,
            lifecycle_store=self._context_lifecycle_store,
            cloud_artifacts=cloud_artifacts,
            local_store=self._provider_continuation_store,
            session_id=session_id,
        )
        model_step = HarnessModelStep(
            context_compiler=context_compiler,
            available_tools=tool_gateway.model_tools,
            conversation_compactor=context_compiler,
            event_sink=persist_event,
            continuation_sink=prepare_continuation,
            provider_continuation=provider_continuation,
            attempt_number=1,
        )
        orchestrator = SingleAttemptOrchestrator(
            model_gateway,
            LocalPolicyEngine(
                profile=PolicyProfile(task.policy_profile),
                network_profile=effective_network_profile,
                web_search_endpoint=self._settings.web_search_endpoint,
                trusted_local=trusted_local,
            ),
            tool_gateway,
            model_step=model_step,
            synthesize_tool_results=True,
            parallel_safe_tools=tool_gateway.parallel_safe_tools,
            parallel_batch_limits=tool_gateway.parallel_batch_limits,
            max_parallel_tool_calls=3,
            tool_call_resolver=tool_gateway.resolve_model_tool_calls,
            event_sink=persist_event,
        )
        try:
            if continuation is not None:
                attempt_result = orchestrator.continue_approved_tool_call(
                    context,
                    initial_completion=continuation.completion,
                    tool_call=continuation.tool_call,
                    remaining_tool_calls=continuation.remaining_tool_calls,
                    conversation=continuation.conversation,
                    model_calls_used=continuation.model_calls_used,
                    tool_calls_executed=continuation.tool_calls_executed,
                )
            elif clarification is not None:
                attempt_result = orchestrator.continue_clarification(
                    context,
                    tool_call=clarification.tool_call,
                    response=clarification.response,
                    conversation=clarification.conversation,
                    model_calls_used=clarification.model_calls_used,
                    tool_calls_executed=clarification.tool_calls_executed,
                    assistant_message=clarification.assistant_message,
                )
            else:
                attempt_result = orchestrator.run(context)
        except Exception as exc:
            attempt_result = exception_attempt_result(
                exc, error_metadata(exc, clarification, continuation)
            )
        finally:
            cleanup_error = close_tool_gateway(tool_gateway)
        if cleanup_error is not None:
            attempt_result = runtime_cleanup_failure_result(cleanup_error, attempt_result)
        emitted_events = finalize_execution(
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
            started_at=started_at,
        )
        final_session = self._projection_store.get_session(session_id)
        if final_session is None:
            raise WorkerExecutionError("session projection missing after worker execution")
        return ExecutedSession(
            session=final_session,
            events=emitted_events,
            attempt_result=attempt_result,
        )
