from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
    MemoryCandidatePromotionService,
    SessionTitleService,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports import (
    EventStorePort,
    GovernedMemoryStorePort,
    ProjectionStorePort,
    WorkspaceProjectionStorePort,
)

from zebra_agent_worker.cloud_memory_finalization import finalize_cloud_memory
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
) -> tuple[SessionEvent, ...]:
    if recorder.session.status in {
        SessionStatus.CANCELLED,
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
    }:
        return recorder.events
    if attempt_result.outcome not in {
        HarnessAttemptOutcome.SUSPENDED,
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
    elif attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED:
        recorder.append(
            EventType.SESSION_SUSPENDED,
            EventActor.HARNESS,
            {
                "reason": str(attempt_result.metadata.get("stop_reason", "budget")),
                "metadata": attempt_result.metadata,
            },
        )
    # Phase F4: if any tool signalled suspend_after_turn (durable delegation),
    # the parent suspends instead of completing — the child's wakeup will resume it.
    _suspend_signals = [
        event for event in (recorder.events or ())
        if getattr(event, 'event_type', None) is EventType.TOOL_EXECUTION_COMPLETED
        and isinstance(getattr(event, 'payload', {}).get('metadata'), dict)
        and event.payload['metadata'].get('suspend_after_turn') is True
    ]
    _suspended_for_children = bool(
        _suspend_signals and attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    )
    if _suspended_for_children:
        recorder.append(
            EventType.SESSION_SUSPENDED,
            EventActor.HARNESS,
            {
                "reason": "waiting_children",
                "child_task_ids": [
                    signal.payload["metadata"].get("child_task_id")
                    for signal in _suspend_signals
                ],
                "metadata": attempt_result.metadata,
            },
        )
    if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED and not _suspended_for_children:
        if cloud_memory_store is not None:
            if (
                deployment_namespace is None
                or projection_store is None
                or workspace_store is None
            ):
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
        title_event = title_service.generate(
            session=recorder.session,
            events=event_store.list_for_session(recorder.session.session_id),
            next_sequence=recorder.next_sequence,
        )
        if title_event is not None:
            recorder.append_event(title_event)
    return recorder.events


def _finalize_local_memory(
    *,
    recorder: DurableHarnessEventRecorder,
    memory_extraction_service: MemoryCandidateExtractionService,
    memory_promotion_service: MemoryCandidatePromotionService,
    event_store: EventStorePort,
    started_at: datetime,
) -> None:
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
    promotion = memory_promotion_service.promote(
        session=recorder.session,
        source_events=event_store.list_for_session(recorder.session.session_id),
        candidates=extraction.records,
        promoted_at=started_at,
    )
    for event in promotion.events:
        recorder.append_event(event)
