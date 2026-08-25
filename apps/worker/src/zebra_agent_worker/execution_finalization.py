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
    if (
        attempt_result.outcome is HarnessAttemptOutcome.WAITING_EXTERNAL_TOOL
        and attempt_result.metadata.get("stop_reason") == "waiting_client_effect"
    ):
        effect_ids = attempt_result.metadata.get("client_effect_ids")
        recorder.append(
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            EventActor.HARNESS,
            {
                "reason": "waiting_client_effect",
                "client_effect_ids": (
                    effect_ids if isinstance(effect_ids, list) else []
                ),
                "metadata": {
                    "stop_reason": "waiting_client_effect",
                    "assistant_message": attempt_result.metadata.get(
                        "assistant_message"
                    ),
                },
            },
        )
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
        return recorder.events
    else:
        return recorder.events
    if attempt_result.outcome is not HarnessAttemptOutcome.COMPLETED:
        return recorder.events
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
