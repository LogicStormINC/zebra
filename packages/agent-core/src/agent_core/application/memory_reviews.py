from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session


class MemoryReviewAction(StrEnum):
    CONFIRM = "confirm"
    EXPIRE = "expire"


@dataclass(frozen=True)
class MemoryReviewCommand:
    action: MemoryReviewAction
    operator: str
    reason: str
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
        superseded_records = (
            _supersede_records(record, existing_records, reviewed_at)
            if command.action is MemoryReviewAction.CONFIRM
            else ()
        )
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
            actor=EventActor.USER,
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
            },
            created_at=reviewed_at,
        )
        return MemoryReviewResult(
            record=updated_record,
            superseded_records=superseded_records,
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


def _same_scope(left: MemoryRecord, right: MemoryRecord) -> bool:
    if left.visibility is not right.visibility:
        return False
    if left.visibility is MemoryVisibility.REPO:
        return left.repo_id == right.repo_id
    if left.visibility is MemoryVisibility.USER:
        return left.user_id == right.user_id
    return left.tenant_id == right.tenant_id
