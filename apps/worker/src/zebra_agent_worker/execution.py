from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
)
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.harness import (
    HarnessAttempt,
    HarnessContext,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_integrations import build_model_gateway
from agent_runtime import LocalToolGateway
from agent_security import LocalPolicyEngine, NetworkProfile, PolicyProfile, parse_network_profile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteMemoryStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
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
from zebra_agent_worker.control import SessionControlError, SessionControlService
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService
from zebra_agent_worker.tool_run_index import ToolRunIndexer


class WorkerExecutionError(ValueError):
    """Raised when a worker cannot reconstruct or execute a queued session."""


@dataclass(frozen=True)
class ExecutedSession:
    session: Session
    events: tuple[SessionEvent, ...]
    attempt_result: HarnessAttemptResult


@dataclass(frozen=True)
class _RecoveredTask:
    title: str
    user_input: str
    workspace_root: Path
    policy_profile: str
    tool_profile: ToolProfile
    network_profile: NetworkProfile
    max_attempts: int
    max_model_calls: int | None
    max_tool_calls: int | None


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
        self._control_service = SessionControlService(database_path)
        self._model_call_indexer = ModelCallIndexer(SQLiteModelCallStore(database_path))
        self._tool_run_indexer = ToolRunIndexer(
            SQLiteToolRunStore(database_path),
            SQLiteArtifactPayloadStore(database_path),
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
        task = _recover_task(
            session_events,
            workspace=claimed.recovery.workspace,
            fallback_title=claimed.recovery.session.title,
        )
        model_gateway = build_model_gateway(self._settings)
        tool_gateway = LocalToolGateway(
            task.workspace_root,
            model_gateway=model_gateway,
            tool_profile=task.tool_profile,
        )
        context_compiler = LocalContextCompiler()
        orchestrator = SingleAttemptOrchestrator(
            model_gateway,
            LocalPolicyEngine(
                profile=PolicyProfile(task.policy_profile),
                network_profile=task.network_profile,
            ),
            tool_gateway,
            model_step=HarnessModelStep(
                context_compiler=context_compiler,
                available_tools=tool_gateway.model_tools,
                conversation_compactor=context_compiler,
            ),
            synthesize_tool_results=True,
            parallel_safe_tools=tool_gateway.parallel_safe_tools,
            parallel_batch_limits=tool_gateway.parallel_batch_limits,
            max_parallel_tool_calls=3,
        )
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
                confirmed_memories=list_confirmed_repo_memories(
                    self._database_path,
                    repo_id=str(task.workspace_root.resolve()),
                ),
            ),
            session=claimed.recovery.session,
            attempt=HarnessAttempt(number=1, started_at=started_at),
        )
        try:
            continuation = recover_approved_continuation(session_events)
        except ApprovedContinuationError as exc:
            tool_gateway.close()
            self._claim_service.release_claim(claimed)
            raise WorkerExecutionError(str(exc)) from exc
        if continuation is not None:
            claimed = self._mark_approved_continuation_started(
                claimed,
                tool_name=continuation.tool_call.name,
                tool_call_id=str(continuation.tool_call.tool_call_id),
                started_at=started_at,
            )
        context = HarnessContext(
            task=context.task,
            session=claimed.recovery.session,
            attempt=context.attempt,
        )
        try:
            attempt_result = (
                orchestrator.continue_approved_tool_call(
                    context,
                    initial_completion=continuation.completion,
                    tool_call=continuation.tool_call,
                    remaining_tool_calls=continuation.remaining_tool_calls,
                    conversation=continuation.conversation,
                    model_calls_used=continuation.model_calls_used,
                    tool_calls_executed=continuation.tool_calls_executed,
                )
                if continuation is not None
                else orchestrator.run(context)
            )
        finally:
            tool_gateway.close()
        emitted_events = _append_execution_events(
            session=claimed.recovery.session,
            attempt_result=attempt_result,
            memory_extraction_service=self._memory_extraction_service,
            event_store=self._event_store,
            projection_store=self._projection_store,
            workspace_projection=claimed.recovery.workspace,
            workspace_store=self._workspace_store,
            model_call_indexer=self._model_call_indexer,
            tool_run_indexer=self._tool_run_indexer,
            started_at=started_at,
            attempt_already_started=continuation is not None,
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

    def _mark_approved_continuation_started(
        self,
        claimed: ClaimedSession,
        *,
        tool_name: str,
        tool_call_id: str,
        started_at: datetime,
    ) -> ClaimedSession:
        next_sequence = claimed.recovery.session.current_sequence + 1
        for event_type, payload in (
            (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
            (
                EventType.TOOL_EXECUTION_STARTED,
                {
                    "attempt_number": 1,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "approval_continuation": True,
                },
            ),
        ):
            self._event_store.append(
                SessionEvent.create(
                    session_id=claimed.recovery.session.session_id,
                    sequence=next_sequence,
                    event_type=event_type,
                    actor=EventActor.HARNESS,
                    payload=payload,
                    created_at=started_at,
                )
            )
            next_sequence += 1
        return ClaimedSession(
            recovery=self._recovery_service.recover_session(claimed.recovery.session.session_id),
            lease=claimed.lease,
        )


def _recover_task(
    events: list[SessionEvent],
    *,
    workspace: WorkspaceProjection,
    fallback_title: str,
) -> _RecoveredTask:
    user_input: str | None = None
    task_payload: dict[str, object] | None = None
    for event in events:
        if event.event_type is EventType.USER_MESSAGE_RECEIVED:
            content = event.payload.get("content")
            if isinstance(content, str) and content.strip():
                user_input = content.strip()
        if event.event_type is EventType.TASK_PREPARED:
            task_payload = event.payload
    if user_input is None or task_payload is None:
        raise WorkerExecutionError("queued session is missing bootstrap task input")
    title = task_payload.get("title")
    resolved_title = title.strip() if isinstance(title, str) and title.strip() else fallback_title
    policy_profile = workspace.policy_profile or PolicyProfile.WORKSPACE_WRITE.value
    return _RecoveredTask(
        title=resolved_title,
        user_input=user_input,
        workspace_root=Path(workspace.workspace_root).expanduser().resolve(),
        policy_profile=policy_profile,
        tool_profile=workspace.tool_profile,
        network_profile=parse_network_profile(
            workspace.network_profile,
            domain_allowlist=workspace.network_allowlist,
        ),
        max_attempts=_optional_positive_int(task_payload.get("max_attempts")) or 1,
        max_model_calls=_optional_positive_int(task_payload.get("max_model_calls")),
        max_tool_calls=_optional_positive_int(task_payload.get("max_tool_calls")),
    )


def _append_execution_events(
    *,
    session: Session,
    attempt_result: HarnessAttemptResult,
    memory_extraction_service: MemoryCandidateExtractionService,
    event_store: SQLiteEventStore,
    projection_store: SQLiteProjectionStore,
    workspace_projection: WorkspaceProjection,
    workspace_store: SQLiteWorkspaceProjectionStore,
    model_call_indexer: ModelCallIndexer,
    tool_run_indexer: ToolRunIndexer,
    started_at: datetime,
    attempt_already_started: bool = False,
) -> tuple[SessionEvent, ...]:
    current_session = session
    current_workspace = workspace_projection
    next_sequence = current_session.current_sequence + 1
    events: list[SessionEvent] = []

    def append(event_type: EventType, actor: EventActor, payload: dict[str, object]) -> None:
        nonlocal current_session
        nonlocal current_workspace
        nonlocal next_sequence
        event = SessionEvent.create(
            session_id=current_session.session_id,
            sequence=next_sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
            created_at=started_at,
        )
        next_sequence += 1
        event_store.append(event)
        model_call_indexer.index_event(event)
        tool_run_indexer.index_event(event)
        current_session = apply_event(current_session, event)
        current_workspace = apply_workspace_event(current_workspace, event)
        projection_store.save_session(current_session)
        workspace_store.save_workspace(current_workspace)
        events.append(event)

    if not attempt_already_started:
        append(
            EventType.HARNESS_ATTEMPT_STARTED,
            EventActor.HARNESS,
            {"attempt_number": 1},
        )
    for draft in attempt_result.emitted_events:
        append(draft.event_type, draft.actor, draft.payload)
    if attempt_result.outcome is not HarnessAttemptOutcome.WAITING_APPROVAL:
        append(
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
            session=current_session,
            events=event_store.list_for_session(current_session.session_id),
            next_sequence=next_sequence,
            command=MemoryCandidateExtractionCommand(
                repo_id=_local_repo_id(current_workspace.workspace_root),
                extracted_at=started_at,
            ),
        )
        for event in extraction.events:
            event_store.append(event)
            model_call_indexer.index_event(event)
            tool_run_indexer.index_event(event)
            current_session = apply_event(current_session, event)
            current_workspace = apply_workspace_event(current_workspace, event)
            projection_store.save_session(current_session)
            workspace_store.save_workspace(current_workspace)
            events.append(event)
            next_sequence = event.sequence + 1
    return tuple(events)


def _optional_positive_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if value > 0 else None


def _local_repo_id(workspace_root: str) -> str:
    return str(Path(workspace_root).expanduser().resolve())
