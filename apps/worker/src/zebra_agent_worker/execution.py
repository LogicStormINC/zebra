from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.harness import (
    HarnessAttempt,
    HarnessContext,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_integrations import build_model_gateway
from agent_runtime import LocalToolGateway
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_storage import (
    SQLiteEventStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
)
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.model_call_index import ModelCallIndexer
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
        self._model_call_indexer = ModelCallIndexer(SQLiteModelCallStore(database_path))
        self._tool_run_indexer = ToolRunIndexer(SQLiteToolRunStore(database_path))

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
        task = _recover_task(
            self._event_store.list_for_session(session_id),
            fallback_title=claimed.recovery.session.title,
        )
        attempt_result = SingleAttemptOrchestrator(
            build_model_gateway(self._settings),
            LocalPolicyEngine(profile=PolicyProfile(task.policy_profile)),
            LocalToolGateway(task.workspace_root),
        ).run(
            HarnessContext(
                task=HarnessTask(
                    title=task.title,
                    user_input=task.user_input,
                    max_attempts=task.max_attempts,
                    max_model_calls=task.max_model_calls,
                    max_tool_calls=task.max_tool_calls,
                    workspace_root=task.workspace_root,
                ),
                session=claimed.recovery.session,
                attempt=HarnessAttempt(number=1, started_at=started_at),
            )
        )
        emitted_events = _append_execution_events(
            session=claimed.recovery.session,
            attempt_result=attempt_result,
            event_store=self._event_store,
            projection_store=self._projection_store,
            model_call_indexer=self._model_call_indexer,
            tool_run_indexer=self._tool_run_indexer,
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


def _recover_task(events: list[SessionEvent], *, fallback_title: str) -> _RecoveredTask:
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
    workspace_root = task_payload.get("workspace_root")
    if not isinstance(workspace_root, str) or not workspace_root.strip():
        raise WorkerExecutionError("queued session is missing workspace_root")
    title = task_payload.get("title")
    resolved_title = title.strip() if isinstance(title, str) and title.strip() else fallback_title
    policy_profile = task_payload.get("policy_profile")
    if not isinstance(policy_profile, str) or not policy_profile.strip():
        policy_profile = PolicyProfile.WORKSPACE_WRITE.value
    return _RecoveredTask(
        title=resolved_title,
        user_input=user_input,
        workspace_root=Path(workspace_root).expanduser().resolve(),
        policy_profile=policy_profile,
        max_attempts=_optional_positive_int(task_payload.get("max_attempts")) or 1,
        max_model_calls=_optional_positive_int(task_payload.get("max_model_calls")),
        max_tool_calls=_optional_positive_int(task_payload.get("max_tool_calls")),
    )


def _append_execution_events(
    *,
    session: Session,
    attempt_result: HarnessAttemptResult,
    event_store: SQLiteEventStore,
    projection_store: SQLiteProjectionStore,
    model_call_indexer: ModelCallIndexer,
    tool_run_indexer: ToolRunIndexer,
    started_at: datetime,
) -> tuple[SessionEvent, ...]:
    current_session = session
    next_sequence = current_session.current_sequence + 1
    events: list[SessionEvent] = []

    def append(event_type: EventType, actor: EventActor, payload: dict[str, object]) -> None:
        nonlocal current_session
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
        projection_store.save_session(current_session)
        events.append(event)

    append(
        EventType.HARNESS_ATTEMPT_STARTED,
        EventActor.HARNESS,
        {"attempt_number": 1},
    )
    for draft in attempt_result.emitted_events:
        append(draft.event_type, draft.actor, draft.payload)
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
    return tuple(events)


def _optional_positive_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if value > 0 else None
