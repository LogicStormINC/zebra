from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
)
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.harness import (
    HarnessAttempt,
    HarnessContext,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessEventDraft,
)
from agent_integrations import build_model_gateway
from agent_runtime import LocalToolGateway
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteMemoryStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteProviderContinuationStore,
    SQLiteSessionHistory,
    SQLiteToolRunStore,
    SQLiteWorkspaceProjectionStore,
    list_confirmed_repo_memories,
)
from zebra_agent_config import ZebraAgentSettings, load_settings

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
    recover_provider_continuation,
)
from zebra_agent_worker.continuation_lifecycle import (
    mark_approved_continuation_started,
    mark_clarification_continuation_started,
)
from zebra_agent_worker.control import SessionControlError, SessionControlService
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.runtime_authority import (
    close_tool_gateway,
    persist_runtime_authority,
    runtime_cleanup_failure_result,
)
from zebra_agent_worker.runtime_factory import build_runtime
from zebra_agent_worker.task_recovery import recover_task
from zebra_agent_worker.tool_run_index import ToolRunIndexer


class WorkerExecutionError(ValueError):
    """Raised when a worker cannot reconstruct or execute a queued session."""


@dataclass(frozen=True)
class ExecutedSession:
    session: Session
    events: tuple[SessionEvent, ...]
    attempt_result: HarnessAttemptResult


class SessionExecutionService:
    def __init__(
        self,
        *,
        database_path: Path,
        claim_service: SessionClaimService,
        resume_service: SessionResumeService,
        settings: ZebraAgentSettings | None = None,
    ) -> None:
        self._database_path = database_path
        self._claim_service = claim_service
        self._resume_service = resume_service
        self._settings = settings or load_settings()
        self._event_store = SQLiteEventStore(database_path)
        self._projection_store = SQLiteProjectionStore(database_path)
        self._workspace_store = SQLiteWorkspaceProjectionStore(database_path)
        self._recovery_service = SessionRecoveryService(
            self._event_store,
            self._projection_store,
            self._workspace_store,
        )
        self._control_service = SessionControlService(database_path, settings=self._settings)
        self._model_call_indexer = ModelCallIndexer(SQLiteModelCallStore(database_path))
        self._artifact_payload_store = SQLiteArtifactPayloadStore(database_path)
        self._context_lifecycle_store = SQLiteContextLifecycleStore(database_path)
        self._provider_continuation_store = SQLiteProviderContinuationStore(database_path)
        self._tool_run_indexer = ToolRunIndexer(
            SQLiteToolRunStore(database_path),
            self._artifact_payload_store,
        )
        self._memory_extraction_service = MemoryCandidateExtractionService(
            SQLiteMemoryStore(database_path)
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
        resumed = self._resume_service.resume_session(
            session_id,
            worker_id=worker_id,
            resumed_at=started_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        claimed = resumed.claimed
        try:
            restored = self._control_service.restore_suspended_workspace(
                session_id,
                resumed_at=started_at,
            )
        except SessionControlError as exc:
            self._claim_service.release_claim(claimed)
            raise WorkerExecutionError(str(exc)) from exc
        if restored is not None:
            claimed = ClaimedSession(
                recovery=self._recovery_service.recover_session(session_id),
                lease=claimed.lease,
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
            )
        except (FileNotFoundError, ValueError) as exc:
            self._claim_service.release_claim(claimed)
            raise WorkerExecutionError(str(exc)) from exc
        try:
            model_gateway = build_model_gateway(self._settings)
        except ValueError:
            self._claim_service.release_claim(claimed)
            raise
        runtime_handle = None
        try:
            runtime = build_runtime(
                self._settings,
                self._database_path,
                workspace_root=task.workspace_root,
                network_profile=task.network_profile.name.value,
                session_id=str(session_id),
                attempt_number=1,
            )
            runtime_handle = runtime.provision(workspace_root=str(task.workspace_root))
            authority = runtime_handle.authority
            persisted_digest = claimed.recovery.workspace.runtime_spec_digest
            if (
                authority is not None
                and persisted_digest is not None
                and persisted_digest != authority.spec_digest
            ):
                raise WorkerExecutionError(
                    "configured runtime authority differs from session authority"
                )
            authority_recorder = DurableHarnessEventRecorder(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                event_store=self._event_store,
                projection_store=self._projection_store,
                workspace_store=self._workspace_store,
                model_call_indexer=self._model_call_indexer,
                tool_run_indexer=self._tool_run_indexer,
            )
            if persist_runtime_authority(authority_recorder, authority, created_at=started_at):
                claimed = ClaimedSession(
                    recovery=self._recovery_service.recover_session(session_id),
                    lease=claimed.lease,
                )
            tool_gateway = LocalToolGateway(
                task.workspace_root,
                model_gateway=model_gateway,
                tool_profile=task.tool_profile,
                web_search_endpoint=self._settings.web_search_endpoint,
                skill_roots=self._settings.skill_roots,
                mcp_servers=self._settings.mcp_servers,
                mcp_allowlist=task.mcp_allowlist,
                session_history=SQLiteSessionHistory(self._database_path),
                current_session_id=str(session_id),
                runtime=runtime,
                runtime_handle=runtime_handle,
                artifact_payload_store=self._artifact_payload_store,
            )
        except Exception as exc:
            cleanup_error = None
            if runtime_handle is not None:
                try:
                    runtime.destroy(runtime_handle)
                except Exception as error:
                    cleanup_error = error
            self._claim_service.release_claim(claimed)
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
                network_profile=task.network_profile.name.value,
                network_allowlist=task.network_profile.domain_allowlist,
                mcp_allowlist=tuple(tool.name for tool in tool_gateway.effective_mcp_tools),
                confirmed_memories=list_confirmed_repo_memories(
                    self._database_path,
                    repo_id=str(task.workspace_root.resolve()),
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
            self._claim_service.release_claim(claimed)
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
        recorder = DurableHarnessEventRecorder(
            session=claimed.recovery.session,
            workspace=claimed.recovery.workspace,
            event_store=self._event_store,
            projection_store=self._projection_store,
            workspace_store=self._workspace_store,
            model_call_indexer=self._model_call_indexer,
            tool_run_indexer=self._tool_run_indexer,
        )
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

        def persist_continuation(
            reference: ProviderContinuationRef,
            payload: bytes | None,
            maximum_ttl_seconds: int | None,
        ) -> str | None:
            if payload is None:
                return None
            artifact = self._provider_continuation_store.store(
                tenant_id="local",
                session_id=str(session_id),
                reference=reference,
                opaque_payload=payload,
                maximum_ttl_seconds=maximum_ttl_seconds,
            )
            return artifact.artifact_id

        model_step = HarnessModelStep(
            context_compiler=context_compiler,
            available_tools=tool_gateway.model_tools,
            conversation_compactor=context_compiler,
            event_sink=persist_event,
            continuation_sink=persist_continuation,
            provider_continuation=provider_continuation,
            attempt_number=1,
        )
        orchestrator = SingleAttemptOrchestrator(
            model_gateway,
            LocalPolicyEngine(
                profile=PolicyProfile(task.policy_profile),
                network_profile=task.network_profile,
                web_search_endpoint=self._settings.web_search_endpoint,
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
            attempt_result = HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="model execution failed",
                metadata={
                    "stop_reason": "model_execution_failed",
                    "error_type": type(exc).__name__,
                    "model_calls_used": (
                        clarification.model_calls_used + 1
                        if clarification is not None
                        else continuation.model_calls_used + 1
                        if continuation is not None
                        else 1
                    ),
                    "tool_calls_executed": (
                        clarification.tool_calls_executed
                        if clarification is not None
                        else continuation.tool_calls_executed
                        if continuation is not None
                        else 0
                    ),
                },
            )
        finally:
            cleanup_error = close_tool_gateway(tool_gateway)
        if cleanup_error is not None:
            attempt_result = runtime_cleanup_failure_result(cleanup_error, attempt_result)
        emitted_events = _finalize_execution(
            recorder=recorder,
            attempt_result=attempt_result,
            memory_extraction_service=self._memory_extraction_service,
            event_store=self._event_store,
            started_at=started_at,
        )
        final_session = self._projection_store.get_session(session_id)
        if final_session is None:
            raise WorkerExecutionError("session projection missing after worker execution")
        self._claim_service.release_claim(claimed)
        return ExecutedSession(
            session=final_session,
            events=emitted_events,
            attempt_result=attempt_result,
        )

def _finalize_execution(
    *,
    recorder: DurableHarnessEventRecorder,
    attempt_result: HarnessAttemptResult,
    memory_extraction_service: MemoryCandidateExtractionService,
    event_store: SQLiteEventStore,
    started_at: datetime,
) -> tuple[SessionEvent, ...]:
    if recorder.session.status in {
        SessionStatus.CANCELLED,
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
    }:
        return recorder.events
    if attempt_result.outcome not in {
        HarnessAttemptOutcome.WAITING_APPROVAL,
        HarnessAttemptOutcome.WAITING_INPUT,
    }:
        recorder.append(
            EventType.SESSION_COMPLETED
            if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
            else EventType.SESSION_FAILED,
            EventActor.HARNESS,
            {
                "attempt_number": 1,
                "summary": attempt_result.summary,
                "metadata": attempt_result.metadata,
            },
        )
    if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED:
        extraction = memory_extraction_service.extract(
            session=recorder.session,
            events=event_store.list_for_session(recorder.session.session_id),
            next_sequence=recorder.next_sequence,
            command=MemoryCandidateExtractionCommand(
                repo_id=str(Path(recorder.workspace.workspace_root).expanduser().resolve()),
                extracted_at=started_at,
            ),
        )
        for event in extraction.events:
            recorder.append_event(event)
    return recorder.events
