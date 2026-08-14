from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
    MemoryCandidatePromotionService,
    SessionTitleService,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.runtime import RuntimeSnapshot
from agent_storage import SQLiteEventStore

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


def finalize_execution(
    *,
    recorder: DurableHarnessEventRecorder,
    attempt_result: HarnessAttemptResult,
    memory_extraction_service: MemoryCandidateExtractionService,
    memory_promotion_service: MemoryCandidatePromotionService,
    title_service: SessionTitleService,
    event_store: SQLiteEventStore,
    started_at: datetime,
    suspension_snapshot: RuntimeSnapshot | None = None,
    completion_sink: Callable[[SessionEvent], SessionEvent] | None = None,
    attempt_number: int = 1,
) -> tuple[SessionEvent, ...]:
    if recorder.session.status in {
        SessionStatus.CANCELLED,
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
    }:
        return recorder.events
    if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED:
        completed_session = recorder.session.model_copy(update={"status": SessionStatus.COMPLETED})
        extraction = memory_extraction_service.extract(
            session=completed_session,
            events=event_store.list_for_session(recorder.session.session_id),
            next_sequence=recorder.next_sequence,
            command=MemoryCandidateExtractionCommand(
                repo_id=str(Path(recorder.workspace.workspace_root).expanduser().resolve()),
                extracted_at=started_at,
            ),
        )
        for event in extraction.events:
            recorder.append_event(event)
        completed_session = recorder.session.model_copy(update={"status": SessionStatus.COMPLETED})
        promotion = memory_promotion_service.promote(
            session=completed_session,
            source_events=event_store.list_for_session(recorder.session.session_id),
            candidates=extraction.records,
            promoted_at=started_at,
        )
        for event in promotion.events:
            recorder.append_event(event)
        title_event = title_service.generate(
            session=recorder.session.model_copy(update={"status": SessionStatus.COMPLETED}),
            events=event_store.list_for_session(recorder.session.session_id),
            next_sequence=recorder.next_sequence,
        )
        if title_event is not None:
            recorder.append_event(title_event)
        completion_event = SessionEvent.create(
            session_id=recorder.session.session_id,
            sequence=recorder.next_sequence,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": attempt_number,
                "summary": attempt_result.summary,
                "metadata": attempt_result.metadata,
            },
        )
        if completion_sink is None:
            recorder.append_event(completion_event)
        else:
            recorder.accept_persisted_event(completion_sink(completion_event))
    elif attempt_result.outcome not in {
        HarnessAttemptOutcome.SUSPENDED,
        HarnessAttemptOutcome.WAITING_APPROVAL,
        HarnessAttemptOutcome.WAITING_INPUT,
    }:
        recorder.append(
            EventType.SESSION_FAILED,
            EventActor.HARNESS,
            {
                "attempt_number": attempt_number,
                "summary": attempt_result.summary,
                "metadata": attempt_result.metadata,
            },
        )
    elif attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED:
        snapshot_payload = (
            {}
            if suspension_snapshot is None
            else {
                "runtime_name": suspension_snapshot.runtime_name,
                "snapshot_id": suspension_snapshot.snapshot_id,
                "snapshot_path": suspension_snapshot.snapshot_path,
            }
        )
        recorder.append(
            EventType.SESSION_SUSPENDED,
            EventActor.HARNESS,
            {
                "reason": str(attempt_result.metadata.get("stop_reason", "budget")),
                "metadata": attempt_result.metadata,
                **snapshot_payload,
            },
        )
    return recorder.events
