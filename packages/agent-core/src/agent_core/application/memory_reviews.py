from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session

_SINGLE_ACTIVE_MEMORY_TYPES = frozenset(
    {
        MemoryType.PROJECT_RULE,
        MemoryType.ARCHITECTURE_FACT,
        MemoryType.PROCEDURE,
    }
)


class MemoryReviewAction(StrEnum):
    CONFIRM = "confirm"
    EXPIRE = "expire"


@dataclass(frozen=True)
class MemoryReviewCommand:
    action: MemoryReviewAction
    operator: str
    reason: str
    actor: EventActor = EventActor.USER
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.operator.strip():
            raise ValueError("memory review operator must not be blank")
        if not self.reason.strip():
            raise ValueError("memory review reason must not be blank")
        if self.created_at is not None and self.created_at.tzinfo is None:
            raise ValueError("memory review created_at must be timezone-aware")


@dataclass(frozen=True)
class MemoryReviewResult:
    record: MemoryRecord
    event: SessionEvent
    superseded_records: tuple[MemoryRecord, ...] = ()
    duplicate_of: MemoryRecord | None = None


@dataclass(frozen=True)
class MemoryReviewService:
    def review(
        self,
        *,
        session: Session,
        record: MemoryRecord,
        next_sequence: int,
        command: MemoryReviewCommand,
        existing_records: tuple[MemoryRecord, ...] = (),
    ) -> MemoryReviewResult:
        """SQLite-compatible wrapper around the pure review planner."""
        return self.plan(
            session=session,
            record=record,
            next_sequence=next_sequence,
            command=command,
            existing_records=existing_records,
        )

    def plan(
        self,
        *,
        session: Session,
        record: MemoryRecord,
        next_sequence: int,
        command: MemoryReviewCommand,
        existing_records: tuple[MemoryRecord, ...] = (),
    ) -> MemoryReviewResult:
        if record.source_session_id != session.session_id:
            raise ValueError("memory review requires the source session to match")
        if record.status is not MemoryStatus.CANDIDATE:
            raise ValueError("memory review requires a candidate memory")
        if next_sequence != session.current_sequence + 1:
            raise ValueError("memory review sequence must follow current session")
        next_status = (
            MemoryStatus.CONFIRMED
            if command.action is MemoryReviewAction.CONFIRM
            else MemoryStatus.EXPIRED
        )
        reviewed_at = command.created_at or datetime.now(session.updated_at.tzinfo)
        duplicate_of = (
            _duplicate_confirmed_record(record, existing_records)
            if command.action is MemoryReviewAction.CONFIRM
            else None
        )
        if duplicate_of is not None:
            next_status = MemoryStatus.EXPIRED
        superseded_records: tuple[MemoryRecord, ...] = ()
        if command.action is MemoryReviewAction.CONFIRM and duplicate_of is None:
            superseded_records = _supersede_records(record, existing_records, reviewed_at)
        updated_record = record.model_copy(
            update={
                "status": next_status,
                "updated_at": reviewed_at,
            }
        )
        event = SessionEvent.create(
            session_id=session.session_id,
            sequence=next_sequence,
            event_type=EventType.MEMORY_REVIEW_RECORDED,
            actor=command.actor,
            payload={
                "memory_id": str(record.memory_id),
                "memory_type": record.memory_type.value,
                "previous_status": record.status.value,
                "status": next_status.value,
                "operator": command.operator.strip(),
                "reason": command.reason.strip(),
                "superseded_memory_ids": [
                    str(existing.memory_id) for existing in superseded_records
                ],
                "duplicate_of_memory_id": (
                    None if duplicate_of is None else str(duplicate_of.memory_id)
                ),
            },
            created_at=reviewed_at,
        )
        return MemoryReviewResult(
            record=updated_record,
            superseded_records=superseded_records,
            duplicate_of=duplicate_of,
            event=event,
        )


def memory_review_scope_query(record: MemoryRecord) -> MemoryQuery:
    if record.visibility is MemoryVisibility.REPO:
        return MemoryQuery(
            repo_id=record.repo_id,
            visibility=MemoryVisibility.REPO,
            memory_types=(record.memory_type,),
            statuses=(MemoryStatus.CONFIRMED,),
            limit=50,
        )
    if record.visibility is MemoryVisibility.USER:
        return MemoryQuery(
            user_id=record.user_id,
            visibility=MemoryVisibility.USER,
            memory_types=(record.memory_type,),
            statuses=(MemoryStatus.CONFIRMED,),
            limit=50,
        )
    return MemoryQuery(
        tenant_id=record.tenant_id,
        visibility=MemoryVisibility.TENANT,
        memory_types=(record.memory_type,),
        statuses=(MemoryStatus.CONFIRMED,),
        limit=50,
    )


def _supersede_records(
    record: MemoryRecord,
    existing_records: tuple[MemoryRecord, ...],
    reviewed_at: datetime,
) -> tuple[MemoryRecord, ...]:
    if record.memory_type not in _SINGLE_ACTIVE_MEMORY_TYPES:
        return ()
    superseded: list[MemoryRecord] = []
    for existing in existing_records:
        if existing.memory_id == record.memory_id:
            continue
        if existing.status is not MemoryStatus.CONFIRMED:
            continue
        if existing.memory_type is not record.memory_type:
            continue
        if not _same_scope(existing, record):
            continue
        superseded.append(
            existing.model_copy(
                update={
                    "status": MemoryStatus.SUPERSEDED,
                    "superseded_by": record.memory_id,
                    "updated_at": reviewed_at,
                }
            )
        )
    return tuple(superseded)


def _duplicate_confirmed_record(
    record: MemoryRecord,
    existing_records: tuple[MemoryRecord, ...],
) -> MemoryRecord | None:
    normalized_text = _normalize_memory_text(record.text)
    for existing in existing_records:
        if existing.memory_id == record.memory_id:
            continue
        if existing.status is not MemoryStatus.CONFIRMED:
            continue
        if existing.memory_type is not record.memory_type:
            continue
        if not _same_scope(existing, record):
            continue
        if _normalize_memory_text(existing.text) != normalized_text:
            continue
        return existing
    return None


def _same_scope(left: MemoryRecord, right: MemoryRecord) -> bool:
    if left.visibility is not right.visibility:
        return False
    if left.visibility is MemoryVisibility.REPO:
        return left.repo_id == right.repo_id
    if left.visibility is MemoryVisibility.USER:
        return left.user_id == right.user_id
    return left.tenant_id == right.tenant_id


def _normalize_memory_text(text: str) -> str:
    return " ".join(text.strip().split())
