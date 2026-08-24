import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
    MemoryCandidatePromotionService,
    SessionTitleService,
    current_turn,
    memory_extraction_window,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.turns import InteractionMode, derive_turn_id
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports import (
    EventStorePort,
    GovernedMemoryStorePort,
    ProjectionStorePort,
    WorkspaceProjectionStorePort,
)

from zebra_agent_worker.cloud_memory_finalization import finalize_cloud_memory
from zebra_agent_worker.execution_errors import is_sequence_race
from zebra_agent_worker.execution_events import (
    DurableHarnessEventRecorder,
    ExecutionInterrupted,
)


class WorkerExecutionError(ValueError): ...


@dataclass(frozen=True)
class ExecutedSession:
    session: Session
    events: tuple[SessionEvent, ...]
    attempt_result: HarnessAttemptResult


_TURN_TO_SESSION_TERMINAL: dict[EventType, EventType] = {
    EventType.TURN_COMPLETED: EventType.SESSION_COMPLETED,
    EventType.TURN_FAILED: EventType.SESSION_FAILED,
    EventType.TURN_CANCELLED: EventType.SESSION_CANCELLED,
}


def pending_turn_close(events: list[SessionEvent]) -> SessionEvent | None:
    """Detect a crashed two-phase Turn close missing its Segment terminal.

    ADR-026 §4.2: every Segment-closing Turn event is followed by its
    compatible ``SESSION_*`` terminal. When a Worker crashes between the
    two, the recovery path must append the matching terminal instead of
    calling the model again. Applies to completed, failed and cancelled
    closes alike; conversation closes (``closes_segment=false``) wait for
    the next human message and are never reconciled into execution.
    """

    last_close: SessionEvent | None = None
    expected_terminal: EventType | None = None
    for event in events:
        if event.event_type in _TURN_TO_SESSION_TERMINAL:
            last_close = event
            expected_terminal = _TURN_TO_SESSION_TERMINAL[event.event_type]
        elif (
            event.event_type
            in {
                EventType.SESSION_COMPLETED,
                EventType.SESSION_FAILED,
                EventType.SESSION_CANCELLED,
            }
            and event.event_type is expected_terminal
        ):
            # Only the matching Session terminal clears the pending close.
            last_close = None
            expected_terminal = None
    if last_close is None:
        return None
    if last_close.event_type is EventType.TURN_CANCELLED:
        # Control-plane cancellation is inherently a Segment close: the
        # TurnCancelledPayload contract has no closes_segment field.
        return last_close
    if last_close.payload.get("closes_segment") is not True:
        return None
    return last_close


def reconcile_pending_turn_close(
    *,
    recorder: DurableHarnessEventRecorder,
    events: list[SessionEvent],
    started_at: datetime,
) -> ExecutedSession | None:
    """Heal a crashed Turn close; never re-invokes the model."""

    turn_event = pending_turn_close(events)
    if turn_event is None:
        return None
    turn_id = turn_event.payload.get("turn_id")
    summary = turn_event.payload.get("summary") or turn_event.payload.get("reason")
    metadata = turn_event.payload.get("metadata")
    terminal_type = _TURN_TO_SESSION_TERMINAL[turn_event.event_type]
    outcome = (
        HarnessAttemptOutcome.COMPLETED
        if terminal_type is EventType.SESSION_COMPLETED
        else HarnessAttemptOutcome.FAILED
    )
    terminal = recorder.prepare(
        terminal_type,
        EventActor.HARNESS,
        {
            "attempt_number": 1,
            "summary": summary if isinstance(summary, str) else "",
            "metadata": metadata if isinstance(metadata, dict) else {},
        },
        created_at=started_at,
    ).model_copy(
        update={
            "idempotency_key": (
                f"turn-close:{turn_id}" if isinstance(turn_id, str) and turn_id else None
            )
        }
    )
    recorder.append_event(terminal)
    return ExecutedSession(
        session=recorder.session,
        events=recorder.events,
        attempt_result=HarnessAttemptResult(
            outcome=outcome,
            summary=summary if isinstance(summary, str) and summary.strip() else "Turn closed.",
            metadata=metadata if isinstance(metadata, dict) else {},
        ),
    )


def finalize_execution(
    *,
    recorder: DurableHarnessEventRecorder,
    attempt_result: HarnessAttemptResult,
    memory_extraction_service: MemoryCandidateExtractionService | None,
    memory_promotion_service: MemoryCandidatePromotionService | None,
    title_service: SessionTitleService,
    event_store: EventStorePort,
    cloud_memory_store: GovernedMemoryStorePort | None = None,
    deployment_namespace: str | None = None,
    projection_store: ProjectionStorePort | None = None,
    workspace_store: WorkspaceProjectionStorePort | None = None,
    started_at: datetime,
    interaction_mode: InteractionMode = InteractionMode.ONE_SHOT,
) -> tuple[SessionEvent, ...]:
    try:
        return _finalize_execution(
            recorder=recorder,
            attempt_result=attempt_result,
            memory_extraction_service=memory_extraction_service,
            memory_promotion_service=memory_promotion_service,
            title_service=title_service,
            event_store=event_store,
            cloud_memory_store=cloud_memory_store,
            deployment_namespace=deployment_namespace,
            projection_store=projection_store,
            workspace_store=workspace_store,
            started_at=started_at,
            interaction_mode=interaction_mode,
        )
    except ExecutionInterrupted:
        return recorder.events


def _finalize_execution(
    *,
    recorder: DurableHarnessEventRecorder,
    attempt_result: HarnessAttemptResult,
    memory_extraction_service: MemoryCandidateExtractionService | None,
    memory_promotion_service: MemoryCandidatePromotionService | None,
    title_service: SessionTitleService,
    event_store: EventStorePort,
    cloud_memory_store: GovernedMemoryStorePort | None,
    deployment_namespace: str | None,
    projection_store: ProjectionStorePort | None,
    workspace_store: WorkspaceProjectionStorePort | None,
    started_at: datetime,
    interaction_mode: InteractionMode,
) -> tuple[SessionEvent, ...]:
    if recorder.session.status in {
        SessionStatus.CANCELLED,
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
    }:
        return recorder.events
    # Phase F4: a durable delegation suspends the parent BEFORE any terminal
    # event — the session never completes while children are outstanding,
    # and the wakeup resumes it with the real child result.
    child_task_ids = _child_task_ids(attempt_result.metadata)
    if (
        attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
        and attempt_result.metadata.get("stop_reason") == "waiting_children"
        and child_task_ids is not None
    ):
        recorder.append(
            EventType.SESSION_SUSPENDED,
            EventActor.HARNESS,
            {
                "reason": "waiting_children",
                "child_task_ids": child_task_ids,
                "metadata": {
                    "stop_reason": "waiting_children",
                    "assistant_message": attempt_result.metadata.get("assistant_message"),
                },
            },
        )
        return recorder.events
    if attempt_result.outcome not in {
        HarnessAttemptOutcome.SUSPENDED,
        HarnessAttemptOutcome.WAITING_APPROVAL,
        HarnessAttemptOutcome.WAITING_INPUT,
    }:
        _append_turn_close(
            recorder=recorder,
            attempt_result=attempt_result,
            event_store=event_store,
            interaction_mode=interaction_mode,
        )
    elif attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED:
        recorder.append(
            EventType.SESSION_SUSPENDED,
            EventActor.HARNESS,
            {
                "reason": str(attempt_result.metadata.get("stop_reason", "budget")),
                "metadata": attempt_result.metadata,
            },
        )
        return recorder.events
    else:
        return recorder.events
    if attempt_result.outcome is not HarnessAttemptOutcome.COMPLETED:
        return recorder.events
    try:
        if cloud_memory_store is not None:
            if deployment_namespace is None or projection_store is None or workspace_store is None:
                raise ValueError(
                    "cloud Memory finalization requires its complete projection context"
                )
            finalize_cloud_memory(
                recorder=recorder,
                memory_store=cloud_memory_store,
                deployment_namespace=deployment_namespace,
                event_store=event_store,
                projection_store=projection_store,
                workspace_store=workspace_store,
                started_at=started_at,
            )
        else:
            if memory_extraction_service is None or memory_promotion_service is None:
                raise ValueError("local Memory finalization requires writable Memory services")
            _finalize_local_memory(
                recorder=recorder,
                memory_extraction_service=memory_extraction_service,
                memory_promotion_service=memory_promotion_service,
                event_store=event_store,
                started_at=started_at,
            )
    except ValueError as exc:
        # The memory tail spans provider/DB round-trips while the Segment
        # sits in awaiting_turn — exactly when the next human message is
        # admitted. Losing the sequence race is normal: the Turn outcome
        # is already durable and the recovery scan re-drives memory;
        # anything else is a real failure and still raises.
        if not is_sequence_race(exc):
            raise
        print(
            f"memory finalization deferred after sequence race: {exc}",
            file=sys.stderr,
        )
    try:
        title_event = title_service.generate(
            session=recorder.session,
            events=event_store.list_for_session(recorder.session.session_id),
            next_sequence=recorder.next_sequence,
        )
        if title_event is not None:
            recorder.append_event(title_event)
    except ValueError as exc:
        # Titles are best-effort; the cloud recovery scan regenerates a
        # missing title after the race window.
        if not is_sequence_race(exc):
            raise
        print(f"title generation deferred after sequence race: {exc}", file=sys.stderr)
    return recorder.events


def _append_turn_close(
    *,
    recorder: DurableHarnessEventRecorder,
    attempt_result: HarnessAttemptResult,
    event_store: EventStorePort,
    interaction_mode: InteractionMode,
) -> None:
    """Close the executing Turn, then the Segment only on hard boundaries.

    ADR-026: a conversation Task writes ``TURN_COMPLETED(closes_segment=
    false)`` and stays in ``awaiting_turn``; a one-shot (and every legacy
    admission) additionally writes ``SESSION_COMPLETED`` so existing
    terminal consumers keep working. Failures always close the Segment.
    """

    events = (
        event_store.list_for_session(recorder.session.session_id) if event_store is not None else []
    )
    open_turn = current_turn(events) if events else None
    fallback: UUID = (
        events[0].session_id
        if events
        else getattr(recorder.session, "session_id", None) or UUID(int=0)
    )
    turn_id = open_turn.turn_id if open_turn else str(derive_turn_id(fallback, 0))
    turn_index = open_turn.turn_index if open_turn else 0
    if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED:
        closes_segment = interaction_mode is not InteractionMode.CONVERSATION
        recorder.append(
            EventType.TURN_COMPLETED,
            EventActor.HARNESS,
            {
                "turn_id": turn_id,
                "turn_index": turn_index,
                "summary": attempt_result.summary,
                "closes_segment": closes_segment,
                "attempt_number": 1,
                "metadata": attempt_result.metadata,
            },
        )
        if closes_segment:
            recorder.append(
                EventType.SESSION_COMPLETED,
                EventActor.HARNESS,
                {
                    "attempt_number": 1,
                    "summary": attempt_result.summary,
                    "metadata": attempt_result.metadata,
                },
            )
        return
    recorder.append(
        EventType.TURN_FAILED,
        EventActor.HARNESS,
        {
            "turn_id": turn_id,
            "turn_index": turn_index,
            "reason": attempt_result.summary,
            "closes_segment": True,
            "attempt_number": 1,
            "metadata": attempt_result.metadata,
        },
    )
    recorder.append(
        EventType.SESSION_FAILED,
        EventActor.HARNESS,
        {
            "attempt_number": 1,
            "summary": attempt_result.summary,
            "metadata": attempt_result.metadata,
        },
    )


def _child_task_ids(metadata: dict[str, object]) -> list[str] | None:
    """Extract validated waiting-children ids from attempt metadata."""

    raw = metadata.get("child_task_ids")
    if not isinstance(raw, list):
        return None
    ids = [item.strip() if isinstance(item, str) else "" for item in raw]
    if not ids or any(not item for item in ids):
        return None
    return ids


def _finalize_local_memory(
    *,
    recorder: DurableHarnessEventRecorder,
    memory_extraction_service: MemoryCandidateExtractionService,
    memory_promotion_service: MemoryCandidatePromotionService,
    event_store: EventStorePort,
    started_at: datetime,
) -> None:
    events = event_store.list_for_session(recorder.session.session_id)
    # Per-turn extraction window anchored on the previous Turn close: never
    # re-derive candidates a previous turn already extracted, and advance
    # even when a Turn produced zero candidates (ADR-026 §6).
    since_sequence = memory_extraction_window(events)
    extraction = memory_extraction_service.extract(
        session=recorder.session,
        events=events,
        next_sequence=recorder.next_sequence,
        command=MemoryCandidateExtractionCommand(
            repo_id=str(Path(recorder.workspace.workspace_root).expanduser().resolve()),
            extracted_at=started_at,
            since_sequence=since_sequence,
        ),
    )
    for event in extraction.events:
        recorder.append_event(event)
    promotion = memory_promotion_service.promote(
        session=recorder.session,
        source_events=event_store.list_for_session(recorder.session.session_id),
        candidates=extraction.records,
        promoted_at=started_at,
    )
    for event in promotion.events:
        recorder.append_event(event)
