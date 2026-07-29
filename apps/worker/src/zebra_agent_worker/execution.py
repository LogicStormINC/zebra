from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.application import (
    MemoryCandidateExtractionService,
    MemoryCandidatePromotionService,
    SessionTitleService,
)
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.harness import (
    HarnessAttempt,
    HarnessContext,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_integrations import build_model_gateway
from agent_runtime import LocalToolGateway
from agent_security import (
    LocalPolicyEngine,
    PolicyProfile,
    resolve_effective_network_profile,
)
from agent_storage import (
    ControlPlaneStores,
    SQLiteSkillsStateStore,
    list_confirmed_repo_memories,
    sqlite_control_plane_stores,
)
from agent_tools.skills_scope import build_scoped_skill_roots
from zebra_agent_config import (
    ZebraAgentSettings,
    load_settings,
    trusted_local_mode_enabled,
)

import zebra_agent_worker.runtime_setup as runtime_setup
import zebra_agent_worker.session_handoff as handoff
from zebra_agent_worker.approved_continuation import (
    ApprovedContinuationError,
    recover_approved_continuation,
)
from zebra_agent_worker.claims import ClaimedSession, SessionClaimService
from zebra_agent_worker.clarification_continuation import (
    ClarificationContinuationError,
    recover_clarification_continuation,
)
from zebra_agent_worker.context_lifecycle import (
    persist_context_compaction,
    persist_provider_continuation,
    recover_provider_continuation,
)
from zebra_agent_worker.continuation_lifecycle import (
    mark_approved_continuation_started,
    mark_clarification_continuation_started,
)
from zebra_agent_worker.control import SessionControlError, SessionControlService
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    WorkerExecutionError,
    finalize_execution,
)
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.runtime_authority import (
    close_tool_gateway,
    persist_runtime_authority,
    runtime_cleanup_failure_result,
)
from zebra_agent_worker.task_recovery import recover_task
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
        stores: ControlPlaneStores | None = None,
        effect_dispatch: EffectDispatchPort | None = None,
        worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
        deployment_namespace: str | None = None,
    ) -> None:
        self._database_path = database_path
        self._claim_service = claim_service
        self._resume_service = resume_service
        self._settings = settings or load_settings()
        active_stores = stores or sqlite_control_plane_stores(database_path)
        self._event_store = active_stores.events
        self._projection_store = active_stores.sessions
        self._workspace_store = active_stores.workspaces
        self._recovery_service = SessionRecoveryService(
            self._event_store,
            self._projection_store,
            self._workspace_store,
        )
        self._control_service = SessionControlService(
            database_path,
            settings=self._settings,
            stores=active_stores,
        )
        self._artifact_payload_store = active_stores.artifact_payloads
        self._context_lifecycle_store = active_stores.context_lifecycle
        self._provider_continuation_store = active_stores.provider_continuations
        self._model_call_indexer = ModelCallIndexer(active_stores.model_calls)
        self._tool_run_indexer = ToolRunIndexer(
            active_stores.tool_runs, self._artifact_payload_store
        )
        self._projection_recorder_factory = WorkerProjectionRecorderFactory(
            stores=active_stores,
            model_call_indexer=self._model_call_indexer,
            tool_run_indexer=self._tool_run_indexer,
            transaction=worker_projection_transaction,
            deployment_namespace=deployment_namespace,
        )
        self._memory_store = active_stores.memories
        self._memory_extraction_service = MemoryCandidateExtractionService(self._memory_store)
        self._memory_promotion_service = MemoryCandidatePromotionService(self._memory_store)
        self._effect_ledger = active_stores.effects
        self._effect_dispatch = effect_dispatch
        self._session_history = active_stores.session_history
        self._handoff_gate = handoff.SessionHandoffRecoveryGate(
            str(database_path), stores=active_stores
        )

    def execute_session(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        executed_at: datetime | None = None,
        lease_ttl_seconds: int = 30,
    ) -> ExecutedSession:
        started_at = executed_at or datetime.now(UTC)
        lease = self._claim_service.acquire_lease(
            session_id,
            worker_id=worker_id,
            claimed_at=started_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        with LeaseHeartbeat(
            self._claim_service,
            lease,
            lease_ttl_seconds=lease_ttl_seconds,
        ) as heartbeat:
            claimed = self._claim_service.recover_lease(
                lease,
                lease_ttl_seconds=lease_ttl_seconds,
            )
            resumed = self._resume_service.require_resumable(
                claimed,
                release_on_failure=False,
            )
            heartbeat.require_owned()
            return self._execute_claimed_session(
                resumed.claimed,
                worker_id=worker_id,
                started_at=started_at,
                ownership_check=heartbeat.require_owned,
            )

    def _execute_claimed_session(
        self,
        claimed: ClaimedSession,
        *,
        worker_id: str,
        started_at: datetime,
        ownership_check: Callable[[], None],
    ) -> ExecutedSession:
        session_id = claimed.lease.session_id
        try:
            restored = self._control_service.restore_suspended_workspace(
                session_id,
                resumed_at=started_at,
            )
        except SessionControlError as exc:
            raise WorkerExecutionError(str(exc)) from exc
        if restored is not None:
            claimed = ClaimedSession(
                recovery=self._recovery_service.recover_session(session_id),
                lease=claimed.lease,
            )
        recovered_handoff = handoff.recover_worker_handoff(
            self._handoff_gate,
            session_id,
            worker_id=worker_id,
            recovered_at=started_at,
            release=lambda: None,
        )
        session_events = self._event_store.list_for_session(session_id)
        active_context = self._context_lifecycle_store.get_active_capsule(session_id)
        provider_continuation = recover_provider_continuation(
            session_events, self._provider_continuation_store
        )
        try:
            task = recover_task(
                session_events,
                workspace=claimed.recovery.workspace,
                fallback_title=claimed.recovery.session.title,
                attachment_store=self._artifact_payload_store,
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
        try:
            model_gateway = build_model_gateway(self._settings)
        except ValueError:
            raise
        runtime_handle = None
        effect_recorder: list[DurableHarnessEventRecorder] = []
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
                    recovery=self._recovery_service.recover_session(session_id),
                    lease=claimed.lease,
                )
            local_tool_gateway = LocalToolGateway(
                task.workspace_root,
                model_gateway=model_gateway,
                tool_profile=task.tool_profile,
                web_search_endpoint=self._settings.web_search_endpoint,
                skill_roots=build_scoped_skill_roots(
                    system=self._settings.skill_roots_system,
                    admin=self._settings.skill_roots_admin,
                    user=self._settings.skill_roots,
                    repo=self._settings.skill_roots_repo,
                ),
                skills_state=(
                    SQLiteSkillsStateStore(self._settings.skills_state_path)
                    if (
                        self._settings.skill_roots
                        or self._settings.skill_roots_system
                        or self._settings.skill_roots_admin
                        or self._settings.skill_roots_repo
                    )
                    else None
                ),
                mcp_servers=self._settings.mcp_servers,
                mcp_allowlist=task.mcp_allowlist,
                session_history=self._session_history.scoped(task.history_session_ids),
                current_session_id=str(session_id),
                runtime=runtime,
                runtime_handle=runtime_handle,
                artifact_payload_store=self._artifact_payload_store,
                trusted_local=trusted_local,
                web_pipeline_v2=self._settings.web_pipeline_v2,
            )
            tool_gateway = handoff.guard_effectful_tools(
                local_tool_gateway,
                ledger=self._effect_ledger,
                session_id=session_id,
                recovered_handoff=recovered_handoff,
                authority_scope=(
                    f"{task.workspace_root.resolve()}|{task.policy_profile}|"
                    f"{effective_network_profile.name.value}"
                ),
                dispatch=self._effect_dispatch,
                artifacts=self._artifact_payload_store,
                fence=claimed.lease.fence,
                claim_ttl=claimed.lease.expires_at - claimed.lease.heartbeat_at,
                next_event=lambda event_type, actor, payload: effect_recorder[-1].prepare(
                    event_type, actor, payload
                ),
                accept_event=lambda event: effect_recorder[-1].accept_persisted_event(event),
                ownership_check=ownership_check,
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
            task=HarnessTask(
                title=task.title,
                user_input=task.user_input,
                max_attempts=task.max_attempts,
                max_model_calls=task.max_model_calls,
                max_tool_calls=task.max_tool_calls,
                workspace_root=task.workspace_root,
                policy_profile=task.policy_profile,
                tool_profile=task.tool_profile,
                network_profile=effective_network_profile.name.value,
                network_allowlist=effective_network_profile.domain_allowlist,
                mcp_allowlist=tuple(tool.name for tool in tool_gateway.effective_mcp_tools),
                skill_components=tool_gateway.effective_skill_components,
                confirmed_memories=list_confirmed_repo_memories(
                    self._memory_store,
                    repo_id=str(task.workspace_root.resolve()),
                    query_text=task.user_input,
                ),
                attachments=task.attachments,
                runtime_evidence=task.runtime_evidence,
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
            )
        elif clarification is not None:
            claimed = mark_clarification_continuation_started(
                claimed,
                event_store=self._event_store,
                recovery_service=self._recovery_service,
                clarification_id=str(clarification.tool_call.tool_call_id),
                started_at=started_at,
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

        def persist_event(draft: HarnessEventDraft) -> None:
            if draft.event_type is EventType.CONTEXT_COMPACTED:
                persist_context_compaction(
                    draft,
                    recorder=recorder,
                    event_store=self._event_store,
                    lifecycle_store=self._context_lifecycle_store,
                )
            else:
                recorder.append_draft(draft)

        model_step = HarnessModelStep(
            context_compiler=context_compiler,
            available_tools=tool_gateway.model_tools,
            conversation_compactor=context_compiler,
            event_sink=persist_event,
            continuation_sink=lambda reference, payload, ttl: persist_provider_continuation(
                self._provider_continuation_store, session_id, reference, payload, ttl
            ),
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
