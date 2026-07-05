from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_core.application.memory_candidate_sources import (
    candidate_key,
    candidates_from_session_event,
    refresh_targets_from_session_event,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
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
    extracted_at: datetime | None = None


@dataclass(frozen=True)
class MemoryCandidateExtractionResult:
    records: tuple[MemoryRecord, ...]
    events: tuple[SessionEvent, ...]


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
        if session.status is not SessionStatus.COMPLETED:
            raise ValueError("memory candidates can only be extracted from completed sessions")

        records: list[MemoryRecord] = []
        emitted_events: list[SessionEvent] = []
        seen_keys: set[tuple[str, str, tuple[str, ...], str | None, str]] = set()
        refresh_targets: dict[str, tuple[tuple[MemoryType, ...], str]] = {}
        created_at = command.extracted_at or session.updated_at

        for event in events:
            for refresh_target in refresh_targets_from_session_event(event):
                refresh_targets[refresh_target.key] = (
                    refresh_target.memory_types,
                    refresh_target.reason,
                )
            candidates = candidates_from_session_event(
                event,
                repo_id=command.repo_id,
                user_id=command.user_id,
                tenant_id=command.tenant_id,
                created_at=created_at,
            )
            for candidate in candidates:
                record_key = candidate_key(candidate, event)
                if record_key in seen_keys:
                    continue
                seen_keys.add(record_key)
                stored = self._memory_store.upsert(candidate)
                records.append(stored)
                emitted_events.append(
                    SessionEvent.create(
                        session_id=session.session_id,
                        sequence=next_sequence + len(emitted_events),
                        event_type=EventType.MEMORY_CANDIDATE_EXTRACTED,
                        actor=EventActor.HARNESS,
                        payload=_event_payload_for_candidate(stored),
                        created_at=created_at,
                    )
                )

        for stale_record, reason in _stale_confirmed_repo_memories(
            repo_id=command.repo_id,
            memory_store=self._memory_store,
            current_candidates=tuple(records),
            created_at=created_at,
            refresh_targets=tuple(
                (memory_types, reason) for memory_types, reason in refresh_targets.values()
            ),
        ):
            self._memory_store.upsert(stale_record)
            emitted_events.append(
                SessionEvent.create(
                    session_id=session.session_id,
                    sequence=next_sequence + len(emitted_events),
                    event_type=EventType.MEMORY_REVIEW_RECORDED,
                    actor=EventActor.HARNESS,
                    payload={
                        "memory_id": str(stale_record.memory_id),
                        "memory_type": stale_record.memory_type.value,
                        "previous_status": MemoryStatus.CONFIRMED.value,
                        "status": MemoryStatus.EXPIRED.value,
                        "operator": "system",
                        "reason": reason,
                        "superseded_memory_ids": [],
                        "duplicate_of_memory_id": None,
                    },
                    created_at=created_at,
                )
            )

        return MemoryCandidateExtractionResult(
            records=tuple(records),
            events=tuple(emitted_events),
        )


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
    repo_id: str,
    memory_store: MemoryStorePort,
    current_candidates: tuple[MemoryRecord, ...],
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
        confirmed_records = memory_store.list(
            MemoryQuery(
                repo_id=repo_id,
                visibility=MemoryVisibility.REPO,
                memory_types=eligible_types,
                statuses=(MemoryStatus.CONFIRMED,),
                limit=100,
            )
        )
        for record in confirmed_records:
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
