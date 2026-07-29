from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from agent_core.application.memory_candidate_sources import candidates_from_session_event
from agent_core.application.memory_reviews import (
    MemoryReviewAction,
    MemoryReviewCommand,
    MemoryReviewService,
    memory_review_scope_query,
)
from agent_core.domain.events import EventActor, SessionEvent
from agent_core.domain.governed_memories import GovernedMemoryLifecycleMutation
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session
from agent_core.ports.memory_store import MemoryStorePort

_AUTO_PROMOTABLE_TYPES = frozenset(
    {
        MemoryType.PREFERENCE,
        MemoryType.PROCEDURE,
        MemoryType.PROJECT_RULE,
        MemoryType.ARCHITECTURE_FACT,
    }
)


@dataclass(frozen=True)
class MemoryCandidatePromotionResult:
    records: tuple[MemoryRecord, ...]
    events: tuple[SessionEvent, ...]


@dataclass(frozen=True)
class MemoryCandidatePromotionPlan:
    records: tuple[MemoryRecord, ...]
    superseded_records: tuple[MemoryRecord, ...]
    events: tuple[SessionEvent, ...]

    def governed_mutations(
        self,
        *,
        expected_revisions: Mapping[MemoryId, int],
    ) -> tuple[GovernedMemoryLifecycleMutation, ...]:
        promoted = tuple(
            GovernedMemoryLifecycleMutation.from_status_update(
                record,
                previous_status=MemoryStatus.CANDIDATE,
                expected_revision=expected_revisions[record.memory_id],
            )
            for record in self.records
        )
        superseded = tuple(
            GovernedMemoryLifecycleMutation.from_status_update(
                record,
                previous_status=MemoryStatus.CONFIRMED,
                expected_revision=expected_revisions[record.memory_id],
            )
            for record in self.superseded_records
        )
        return promoted + superseded


@dataclass(frozen=True)
class MemoryCandidatePromotionPlanner:
    def plan(
        self,
        *,
        session: Session,
        source_events: list[SessionEvent],
        candidates: tuple[MemoryRecord, ...],
        promoted_at: datetime,
        existing_records: tuple[MemoryRecord, ...] = (),
    ) -> MemoryCandidatePromotionPlan:
        events_by_sequence = {
            event.sequence: event
            for event in source_events
            if event.session_id == session.session_id
        }
        reviewed_records: list[MemoryRecord] = []
        superseded_records: list[MemoryRecord] = []
        review_events: list[SessionEvent] = []
        projected_session = session
        effective_existing = list(existing_records)
        for candidate in candidates:
            source = _reconstructed_source(candidate, events_by_sequence)
            if source is None:
                continue
            existing = _records_in_review_scope(candidate, tuple(effective_existing))
            if _has_conflict(candidate, existing):
                continue
            review = MemoryReviewService().plan(
                session=projected_session,
                record=candidate,
                next_sequence=projected_session.current_sequence + 1,
                command=MemoryReviewCommand(
                    action=MemoryReviewAction.CONFIRM,
                    operator="system:auto-promotion",
                    reason="reconstructed from deterministic local evidence",
                    actor=EventActor.HARNESS,
                    created_at=promoted_at,
                ),
                existing_records=existing,
            )
            superseded_records.extend(review.superseded_records)
            reviewed_records.append(review.record)
            superseded_ids = {record.memory_id for record in review.superseded_records}
            effective_existing = [
                record for record in effective_existing if record.memory_id not in superseded_ids
            ]
            if review.record.status is MemoryStatus.CONFIRMED:
                effective_existing.append(review.record)
            review_events.append(review.event)
            projected_session = projected_session.advance_sequence()
        return MemoryCandidatePromotionPlan(
            records=tuple(reviewed_records),
            superseded_records=tuple(superseded_records),
            events=tuple(review_events),
        )


class MemoryCandidatePromotionService:
    def __init__(self, memory_store: MemoryStorePort) -> None:
        self._memory_store = memory_store

    def promote(
        self,
        *,
        session: Session,
        source_events: list[SessionEvent],
        candidates: tuple[MemoryRecord, ...],
        promoted_at: datetime,
    ) -> MemoryCandidatePromotionResult:
        existing_records = tuple(
            {
                record.memory_id: record
                for candidate in candidates
                for record in self._memory_store.list(memory_review_scope_query(candidate))
            }.values()
        )
        plan = MemoryCandidatePromotionPlanner().plan(
            session=session,
            source_events=source_events,
            candidates=candidates,
            promoted_at=promoted_at,
            existing_records=existing_records,
        )
        for superseded in plan.superseded_records:
            self._memory_store.upsert(superseded)
        return MemoryCandidatePromotionResult(
            records=tuple(self._memory_store.upsert(record) for record in plan.records),
            events=plan.events,
        )


def _records_in_review_scope(
    candidate: MemoryRecord,
    records: tuple[MemoryRecord, ...],
) -> tuple[MemoryRecord, ...]:
    def same_scope(record: MemoryRecord) -> bool:
        if record.visibility is not candidate.visibility:
            return False
        if candidate.visibility is MemoryVisibility.REPO:
            return record.repo_id == candidate.repo_id
        if candidate.visibility is MemoryVisibility.USER:
            return record.user_id == candidate.user_id
        return record.tenant_id == candidate.tenant_id

    return tuple(
        record
        for record in records
        if record.memory_type is candidate.memory_type
        and record.status is MemoryStatus.CONFIRMED
        and same_scope(record)
    )


def _reconstructed_source(
    candidate: MemoryRecord,
    events_by_sequence: dict[int, SessionEvent],
) -> SessionEvent | None:
    if candidate.memory_type not in _AUTO_PROMOTABLE_TYPES:
        return None
    if (
        candidate.status is not MemoryStatus.CANDIDATE
        or candidate.repo_id is None
        or candidate.source_event_start is None
        or candidate.source_event_start != candidate.source_event_end
    ):
        return None
    source = events_by_sequence.get(candidate.source_event_start)
    if source is None or source.session_id != candidate.source_session_id:
        return None
    reconstructed = candidates_from_session_event(
        source,
        repo_id=candidate.repo_id,
        user_id=candidate.user_id,
        tenant_id=candidate.tenant_id,
        created_at=candidate.created_at,
    )
    return source if any(_same_candidate(candidate, item) for item in reconstructed) else None


def _same_candidate(left: MemoryRecord, right: MemoryRecord) -> bool:
    return (
        left.memory_type is right.memory_type
        and left.visibility is right.visibility
        and left.repo_id == right.repo_id
        and left.user_id == right.user_id
        and left.tenant_id == right.tenant_id
        and _normalize(left.text) == _normalize(right.text)
    )


def _has_conflict(
    candidate: MemoryRecord,
    existing: tuple[MemoryRecord, ...],
) -> bool:
    candidate_text = _normalize(candidate.text)
    return any(_normalize(record.text) != candidate_text for record in existing)


def _normalize(text: str) -> str:
    return " ".join(text.strip().split()).casefold()
