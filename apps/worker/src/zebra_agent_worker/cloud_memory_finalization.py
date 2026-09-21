"""Fenced governed-Memory finalization for a completed Cloud Worker Session."""

from __future__ import annotations

from datetime import datetime

from agent_core.application import (
    GovernedMemoryScope,
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionPlanner,
    MemoryCandidatePromotionPlanner,
    governed_memory_scope_from_events,
    memory_extraction_window,
)
from agent_core.application.memory_reviews import memory_review_scope_query
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import GovernedMemoryEntry
from agent_core.domain.governed_memory_operations import WorkerMemoryMutationPlan
from agent_core.domain.governed_memory_receipts import GovernedMemoryOperationReceipt
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryRecord
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports import (
    EventStorePort,
    GovernedMemoryStorePort,
    ProjectionStorePort,
    WorkspaceProjectionStorePort,
)
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


def finalize_cloud_memory(
    *,
    recorder: DurableHarnessEventRecorder,
    memory_store: GovernedMemoryStorePort,
    deployment_namespace: str,
    event_store: EventStorePort,
    projection_store: ProjectionStorePort,
    workspace_store: WorkspaceProjectionStorePort,
    started_at: datetime,
    allow_commit: bool = True,
) -> bool:
    """Commit candidate and promotion mutations with their Events in one transaction."""
    authority = recorder.worker_mutation_authority
    if authority is None:
        raise ValueError("cloud Memory finalization requires Worker mutation authority")
    session = recorder.session
    events = event_store.list_for_session(session.session_id)
    completion_revision = memory_completion_revision(events, session)
    if _has_extraction_checkpoint(events, completion_revision):
        return True
    operation_id = _operation_id(session, completion_revision)
    committed = memory_store.get_worker_commit_receipt(
        operation_id,
        session_id=session.session_id,
    )
    if committed is not None:
        if recorder.session.current_sequence >= committed.receipt.session_revision:
            _append_extraction_checkpoint(
                recorder,
                completion_revision=completion_revision,
                events=events,
            )
            return True
        if authority.expected_stream_revision != committed.receipt.event_sequences[0] - 1:
            raise ValueError("cloud Memory receipt cannot be accepted from a stale authority")
        _accept_receipt(
            recorder=recorder,
            receipt=committed.receipt,
            event_store=event_store,
            projection_store=projection_store,
            workspace_store=workspace_store,
        )
        _append_extraction_checkpoint(
            recorder,
            completion_revision=completion_revision,
            events=event_store.list_for_session(session.session_id),
        )
        return True
    if authority.expected_stream_revision < completion_revision:
        raise ValueError("cloud Memory finalization authority precedes the closed Turn")
    memory_scope = governed_memory_scope_from_events(
        events,
        fallback_repo_id=str(recorder.workspace.workspace_root),
    )
    if memory_scope is None:
        raise ValueError("cloud Memory principal scope is absent or ambiguous")
    confirmed = memory_store.list_for_worker(
        memory_scope.query(limit=500),
        authority=authority,
    )
    extraction = MemoryCandidateExtractionPlanner().plan(
        session=session,
        events=events,
        next_sequence=recorder.next_sequence,
        command=_extraction_command(recorder, started_at, memory_scope, events),
        confirmed_records=tuple(entry.record for entry in confirmed),
    )
    if not extraction.records and not extraction.stale_records:
        if allow_commit:
            _append_extraction_checkpoint(
                recorder,
                completion_revision=completion_revision,
                events=events,
            )
        return True
    existing_entries = _review_scope_entries(
        extraction.records,
        memory_store=memory_store,
        authority=authority,
    )
    promotion = MemoryCandidatePromotionPlanner().plan(
        session=_advance(session, extraction.events),
        source_events=[*events, *extraction.events],
        candidates=extraction.records,
        promoted_at=started_at,
        existing_records=tuple(entry.record for entry in existing_entries),
    )
    expected_revisions = {entry.record.memory_id: entry.revision for entry in confirmed}
    expected_revisions.update(
        {entry.record.memory_id: entry.revision for entry in existing_entries}
    )
    expected_revisions.update({record.memory_id: 1 for record in extraction.records})
    creations, stale = extraction.governed_mutations(expected_revisions=expected_revisions)
    plan = WorkerMemoryMutationPlan.create(
        deployment_namespace=deployment_namespace,
        operation_id=operation_id,
        session_id=session.session_id,
        expected_stream_revision=authority.expected_stream_revision,
        creations=creations,
        lifecycle_mutations=(
            *stale,
            *promotion.governed_mutations(expected_revisions=expected_revisions),
        ),
        events=(*extraction.events, *promotion.events),
    )
    if not allow_commit:
        return False
    try:
        operation_receipt = memory_store.commit_worker_candidates(plan, authority=authority).receipt
    except Exception:
        reconciled = memory_store.get_worker_commit_receipt(
            operation_id,
            session_id=session.session_id,
        )
        if reconciled is None:
            raise
        operation_receipt = reconciled.receipt
    _accept_receipt(
        recorder=recorder,
        receipt=operation_receipt,
        event_store=event_store,
        projection_store=projection_store,
        workspace_store=workspace_store,
    )
    _append_extraction_checkpoint(
        recorder,
        completion_revision=completion_revision,
        events=event_store.list_for_session(session.session_id),
    )
    return True


def _has_extraction_checkpoint(events: list[SessionEvent], completion_revision: int) -> bool:
    return any(
        event.event_type is EventType.MEMORY_EXTRACTION_COMPLETED
        and event.payload.get("completion_revision") == completion_revision
        for event in events
    )


def _append_extraction_checkpoint(
    recorder: DurableHarnessEventRecorder,
    *,
    completion_revision: int,
    events: list[SessionEvent],
) -> None:
    if _has_extraction_checkpoint(events, completion_revision):
        return
    covered = [
        event
        for event in events
        if event.sequence > completion_revision
        and event.event_type
        in {EventType.MEMORY_CANDIDATE_EXTRACTED, EventType.MEMORY_REVIEW_RECORDED}
    ]
    candidate_count = sum(
        event.event_type is EventType.MEMORY_CANDIDATE_EXTRACTED for event in covered
    )
    lifecycle_count = sum(event.event_type is EventType.MEMORY_REVIEW_RECORDED for event in covered)
    recorder.append_event(
        SessionEvent.create(
            session_id=recorder.session.session_id,
            sequence=recorder.next_sequence,
            event_type=EventType.MEMORY_EXTRACTION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "completion_revision": completion_revision,
                "candidate_count": candidate_count,
                "lifecycle_count": lifecycle_count,
                "outcome": (
                    "committed" if candidate_count or lifecycle_count else "no_eligible_memory"
                ),
            },
            idempotency_key=f"memory-extraction:{completion_revision}",
        )
    )


def _accept_receipt(
    *,
    recorder: DurableHarnessEventRecorder,
    receipt: GovernedMemoryOperationReceipt,
    event_store: EventStorePort,
    projection_store: ProjectionStorePort,
    workspace_store: WorkspaceProjectionStorePort,
) -> None:
    authority = recorder.worker_mutation_authority
    assert authority is not None
    committed = tuple(
        event
        for event in event_store.read_since(
            recorder.session.session_id, authority.expected_stream_revision
        )
        if event.event_id in receipt.event_ids
    )
    if tuple(event.event_id for event in committed) != receipt.event_ids:
        raise ValueError("cloud Memory receipt Events are unavailable after commit")
    receipt_revision = receipt.session_revision
    stored_session = projection_store.get_session(recorder.session.session_id)
    stored_workspace = workspace_store.get_workspace(recorder.session.session_id)
    if stored_session is None or stored_workspace is None:
        raise ValueError("cloud Memory commit did not preserve Session projections")
    if stored_session.current_sequence > receipt_revision:
        # Events committed after the receipt (e.g. the next human message)
        # advanced the durable projection past it. The receipt replay is
        # compared against the projection AT THE RECEIPT REVISION — never
        # against the pre-commit authority revision nor the ahead head.
        all_events = event_store.list_for_session(recorder.session.session_id)
        at_receipt = [event for event in all_events if event.sequence <= receipt_revision]
        stored_session = rebuild_session(at_receipt)
        stored_workspace = rebuild_workspace(at_receipt)
    recorder.accept_committed_events(
        committed,
        session=stored_session,
        workspace=stored_workspace,
    )
    if hasattr(recorder, "refresh_tail"):
        # Adopt any already-committed later tail into recorder memory
        # only; their primary projections were written by their committer.
        recorder.refresh_tail()


def memory_completion_revision(events: list[SessionEvent], session: Session) -> int:
    """The stream revision the Memory commit must anchor on.

    ADR-026: v2 streams anchor on the latest Turn close (the Segment
    terminal for one-shot, the latest ``TURN_COMPLETED`` for conversation
    Tasks, which sit in ``awaiting_turn``). Legacy streams keep requiring
    exactly one ``SESSION_COMPLETED``.
    """

    if session.status not in {SessionStatus.COMPLETED, SessionStatus.AWAITING_TURN}:
        raise ValueError("cloud Memory finalization requires a closed Turn")
    closes = [
        event
        for event in events
        if event.event_type in {EventType.TURN_COMPLETED, EventType.SESSION_COMPLETED}
    ]
    if closes:
        return closes[-1].sequence
    raise ValueError("cloud Memory finalization requires one completed Session Event")


def _operation_id(session: Session, completion_revision: int) -> str:
    return f"worker-memory:{session.session_id}:{completion_revision}"


def _advance(session: Session, events: tuple[SessionEvent, ...]) -> Session:
    for _ in events:
        session = session.advance_sequence()
    return session


def _review_scope_entries(
    candidates: tuple[MemoryRecord, ...],
    *,
    memory_store: GovernedMemoryStorePort,
    authority: WorkerMutationAuthority,
) -> tuple[GovernedMemoryEntry, ...]:
    entries: dict[MemoryId, GovernedMemoryEntry] = {}
    for candidate in candidates:
        for entry in memory_store.list_for_worker(
            memory_review_scope_query(candidate),
            authority=authority,
        ):
            entries[entry.record.memory_id] = entry
    return tuple(entries.values())


def _extraction_command(
    recorder: DurableHarnessEventRecorder,
    started_at: datetime,
    memory_scope: GovernedMemoryScope,
    events: list[SessionEvent],
) -> MemoryCandidateExtractionCommand:
    # Per-turn extraction window anchored on the previous Turn close
    # (ADR-026 §6): advances even for zero-candidate Turns, and a
    # successful extraction's events push it past re-derivation.
    since_sequence = memory_extraction_window(events)
    return MemoryCandidateExtractionCommand(
        repo_id=memory_scope.repo_id,
        user_id=memory_scope.user_id,
        tenant_id=memory_scope.tenant_id,
        extracted_at=started_at,
        authority_issuer=memory_scope.authority_issuer,
        namespace_id=memory_scope.namespace_id,
        definition_id=memory_scope.definition_id,
        since_sequence=since_sequence,
    )
