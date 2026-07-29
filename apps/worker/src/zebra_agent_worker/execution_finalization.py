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
from agent_core.ports import EventStorePort

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
    memory_extraction_service: MemoryCandidateExtractionService,
    memory_promotion_service: MemoryCandidatePromotionService,
    title_service: SessionTitleService,
    event_store: EventStorePort,
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
            started_at=started_at,
        )
    except ExecutionInterrupted:
        return recorder.events


def _finalize_execution(
    *,
    recorder: DurableHarnessEventRecorder,
    attempt_result: HarnessAttemptResult,
    memory_extraction_service: MemoryCandidateExtractionService,
    memory_promotion_service: MemoryCandidatePromotionService,
    title_service: SessionTitleService,
    event_store: EventStorePort,
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
        promotion = memory_promotion_service.promote(
            session=recorder.session,
            source_events=event_store.list_for_session(recorder.session.session_id),
            candidates=extraction.records,
            promoted_at=started_at,
        )
        for event in promotion.events:
            recorder.append_event(event)
        title_event = title_service.generate(
            session=recorder.session,
            events=event_store.list_for_session(recorder.session.session_id),
            next_sequence=recorder.next_sequence,
        )
        if title_event is not None:
            recorder.append_event(title_event)
    return recorder.events
