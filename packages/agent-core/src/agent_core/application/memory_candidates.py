from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from agent_core.application.memory_candidate_sources import (
    candidate_key,
    candidates_from_session_event,
    refresh_targets_from_session_event,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryCreate,
    GovernedMemoryLifecycleMutation,
)
from agent_core.domain.identifiers import AgentDefinitionId, MemoryId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports.memory_store import MemoryStorePort

_SINGLETON_REPO_MEMORY_TYPES = (
    MemoryType.PROJECT_RULE,
    MemoryType.ARCHITECTURE_FACT,
    MemoryType.PROCEDURE,
)


@dataclass(frozen=True)
class MemoryCandidateExtractionCommand:
    repo_id: str
    user_id: str | None = None
    tenant_id: str | None = None
    authority_issuer: str | None = None
    namespace_id: str | None = None
    definition_id: AgentDefinitionId | None = None
    extracted_at: datetime | None = None
    # Per-turn extraction window (ADR-026): only derive candidates from
    # events strictly after this sequence. -1 keeps the legacy full scan.
    since_sequence: int = -1


@dataclass(frozen=True)
class MemoryCandidateExtractionResult:
    records: tuple[MemoryRecord, ...]
    events: tuple[SessionEvent, ...]


@dataclass(frozen=True)
class MemoryCandidateExtractionPlan:
    """Pure candidate mutations; persistence remains an adapter concern."""

    records: tuple[MemoryRecord, ...]
    stale_records: tuple[MemoryRecord, ...]
    events: tuple[SessionEvent, ...]

    def governed_mutations(
        self,
        *,
        expected_revisions: Mapping[MemoryId, int],
    ) -> tuple[
        tuple[GovernedMemoryCreate, ...],
        tuple[GovernedMemoryLifecycleMutation, ...],
    ]:
        return (
            tuple(GovernedMemoryCreate.from_candidate(record) for record in self.records),
            tuple(
                GovernedMemoryLifecycleMutation.from_status_update(
                    record,
                    previous_status=MemoryStatus.CONFIRMED,
                    expected_revision=expected_revisions[record.memory_id],
                )
                for record in self.stale_records
            ),
        )


@dataclass(frozen=True)
class MemoryCandidateExtractionPlanner:
    def plan(
        self,
        *,
        session: Session,
        events: list[SessionEvent],
        next_sequence: int,
        command: MemoryCandidateExtractionCommand,
        confirmed_records: tuple[MemoryRecord, ...] = (),
    ) -> MemoryCandidateExtractionPlan:
        if session.status not in {SessionStatus.COMPLETED, SessionStatus.AWAITING_TURN}:
            raise ValueError(
                "memory candidates can only be extracted after a completed turn"
            )

        records, refresh_targets = _candidate_records_and_refresh_targets(
            events=events,
            command=command,
            created_at=command.extracted_at or session.updated_at,
        )
        stale = _stale_confirmed_repo_memories(
            current_candidates=records,
            confirmed_records=confirmed_records,
            created_at=command.extracted_at or session.updated_at,
            refresh_targets=refresh_targets,
        )
        emitted_events = [
            SessionEvent.create(
                session_id=session.session_id,
                sequence=next_sequence + index,
                event_type=EventType.MEMORY_CANDIDATE_EXTRACTED,
                actor=EventActor.HARNESS,
                payload=_event_payload_for_candidate(record),
                created_at=command.extracted_at or session.updated_at,
            )
            for index, record in enumerate(records)
        ]
        for stale_record, reason in stale:
            emitted_events.append(
                SessionEvent.create(
                    session_id=session.session_id,
                    sequence=next_sequence + len(emitted_events),
                    event_type=EventType.MEMORY_REVIEW_RECORDED,
                    actor=EventActor.HARNESS,
                    payload=_event_payload_for_expiry(stale_record, reason),
                    created_at=command.extracted_at or session.updated_at,
                )
            )
        return MemoryCandidateExtractionPlan(
            records=records,
            stale_records=tuple(record for record, _ in stale),
            events=tuple(emitted_events),
        )


class MemoryCandidateExtractionService:
    def __init__(self, memory_store: MemoryStorePort) -> None:
        self._memory_store = memory_store

    def extract(
        self,
        *,
        session: Session,
        events: list[SessionEvent],
        next_sequence: int,
        command: MemoryCandidateExtractionCommand,
    ) -> MemoryCandidateExtractionResult:
        refresh_targets = _refresh_targets(events)
        confirmed_records = _confirmed_records_for_refresh(
            repo_id=command.repo_id,
            memory_store=self._memory_store,
            refresh_targets=refresh_targets,
        )
        plan = MemoryCandidateExtractionPlanner().plan(
            session=session,
            events=events,
            next_sequence=next_sequence,
            command=command,
            confirmed_records=confirmed_records,
        )
        stored_records = tuple(self._memory_store.upsert(record) for record in plan.records)
        for stale_record in plan.stale_records:
            self._memory_store.upsert(stale_record)

        return MemoryCandidateExtractionResult(
            records=stored_records,
            events=plan.events,
        )


def _candidate_records_and_refresh_targets(
    *,
    events: list[SessionEvent],
    command: MemoryCandidateExtractionCommand,
    created_at: datetime,
) -> tuple[
    tuple[MemoryRecord, ...],
    tuple[tuple[tuple[MemoryType, ...], str], ...],
]:
    records: list[MemoryRecord] = []
    seen_keys: set[tuple[str, str, tuple[str, ...], str | None, str]] = set()
    scope_updates: dict[str, object] = {}
    if command.authority_issuer is not None:
        scope_updates = {
            "authority_issuer": command.authority_issuer,
            "namespace_id": command.namespace_id,
            "definition_id": command.definition_id,
            "tenant_id": None,
            "user_id": None,
            "repo_id": None,
        }
    for event in events:
        if event.sequence <= command.since_sequence:
            continue
        for candidate in candidates_from_session_event(
            event,
            repo_id=command.repo_id,
            user_id=command.user_id,
            tenant_id=command.tenant_id,
            created_at=created_at,
        ):
            record_key = candidate_key(candidate, event)
            if record_key not in seen_keys:
                seen_keys.add(record_key)
                record = (
                    candidate.model_copy(update=scope_updates)
                    if scope_updates
                    else candidate
                )
                records.append(record)
    return tuple(records), _refresh_targets(events)


def _refresh_targets(
    events: list[SessionEvent],
) -> tuple[tuple[tuple[MemoryType, ...], str], ...]:
    targets: dict[str, tuple[tuple[MemoryType, ...], str]] = {}
    for event in events:
        for target in refresh_targets_from_session_event(event):
            targets[target.key] = (target.memory_types, target.reason)
    return tuple(targets.values())


def _confirmed_records_for_refresh(
    *,
    repo_id: str,
    memory_store: MemoryStorePort,
    refresh_targets: tuple[tuple[tuple[MemoryType, ...], str], ...],
) -> tuple[MemoryRecord, ...]:
    confirmed: dict[MemoryId, MemoryRecord] = {}
    for memory_types, _ in refresh_targets:
        eligible_types = tuple(
            memory_type
            for memory_type in memory_types
            if memory_type in _SINGLETON_REPO_MEMORY_TYPES
        )
        if not eligible_types:
            continue
        for record in memory_store.list(
            MemoryQuery(
                repo_id=repo_id,
                visibility=MemoryVisibility.REPO,
                memory_types=eligible_types,
                statuses=(MemoryStatus.CONFIRMED,),
                limit=100,
            )
        ):
            confirmed[record.memory_id] = record
    return tuple(confirmed.values())


def _event_payload_for_candidate(candidate: MemoryRecord) -> dict[str, object]:
    return {
        "memory_id": str(candidate.memory_id),
        "memory_type": candidate.memory_type.value,
        "status": candidate.status.value,
        "visibility": candidate.visibility.value,
        "text": candidate.text,
        "confidence": candidate.confidence,
        "source_event_start": candidate.source_event_start,
        "source_event_end": candidate.source_event_end,
        "repo_id": candidate.repo_id,
        "user_id": candidate.user_id,
        "tenant_id": candidate.tenant_id,
    }


def _stale_confirmed_repo_memories(
    *,
    current_candidates: tuple[MemoryRecord, ...],
    confirmed_records: tuple[MemoryRecord, ...],
    created_at: datetime,
    refresh_targets: tuple[tuple[tuple[MemoryType, ...], str], ...],
) -> tuple[tuple[MemoryRecord, str], ...]:
    current_texts_by_type = _current_candidate_texts_by_type(current_candidates)
    invalidations: dict[str, tuple[MemoryRecord, str]] = {}
    for memory_types, reason in refresh_targets:
        eligible_types = tuple(
            memory_type
            for memory_type in memory_types
            if memory_type in _SINGLETON_REPO_MEMORY_TYPES
        )
        if not eligible_types:
            continue
        for record in confirmed_records:
            if record.memory_type not in eligible_types:
                continue
            current_texts = current_texts_by_type.get(record.memory_type, set())
            if _normalize_memory_text(record.text) in current_texts:
                continue
            invalidations[str(record.memory_id)] = (
                record.model_copy(
                    update={
                        "status": MemoryStatus.EXPIRED,
                        "updated_at": created_at,
                    }
                ),
                reason,
            )
    return tuple(invalidations.values())


def _event_payload_for_expiry(record: MemoryRecord, reason: str) -> dict[str, object]:
    return {
        "memory_id": str(record.memory_id),
        "memory_type": record.memory_type.value,
        "previous_status": MemoryStatus.CONFIRMED.value,
        "status": MemoryStatus.EXPIRED.value,
        "operator": "system",
        "reason": reason,
        "superseded_memory_ids": [],
        "duplicate_of_memory_id": None,
    }


def _current_candidate_texts_by_type(
    current_candidates: tuple[MemoryRecord, ...],
) -> dict[MemoryType, set[str]]:
    current_texts_by_type: dict[MemoryType, set[str]] = {
        memory_type: set() for memory_type in _SINGLETON_REPO_MEMORY_TYPES
    }
    for record in current_candidates:
        if record.memory_type not in _SINGLETON_REPO_MEMORY_TYPES:
            continue
        current_texts_by_type[record.memory_type].add(_normalize_memory_text(record.text))
    return current_texts_by_type


def _normalize_memory_text(text: str) -> str:
    return " ".join(text.strip().split())
