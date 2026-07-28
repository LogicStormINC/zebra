from datetime import UTC, datetime
from uuid import UUID

import pytest
from agent_core.application import (
    MemoryReviewAction,
    MemoryReviewCommand,
    MemoryReviewService,
)
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.sessions import Session, SessionStatus


def test_memory_review_service_confirms_candidate_memory() -> None:
    session = _completed_session()
    record = _candidate_record(session)
    reviewed_at = datetime(2026, 7, 2, 11, 1, tzinfo=UTC)

    result = MemoryReviewService().review(
        session=session,
        record=record,
        next_sequence=4,
        command=MemoryReviewCommand(
            action=MemoryReviewAction.CONFIRM,
            operator="alice",
            reason="validated locally",
            created_at=reviewed_at,
        ),
    )

    assert result.record.status is MemoryStatus.CONFIRMED
    assert result.record.updated_at == reviewed_at
    assert result.event.event_type is EventType.MEMORY_REVIEW_RECORDED
    assert result.event.payload == {
        "memory_id": str(record.memory_id),
        "memory_type": "procedure",
        "previous_status": "candidate",
        "status": "confirmed",
        "operator": "alice",
        "reason": "validated locally",
        "superseded_memory_ids": [],
        "duplicate_of_memory_id": None,
    }


def test_memory_review_service_accepts_explicit_system_actor() -> None:
    session = _completed_session()

    result = MemoryReviewService().review(
        session=session,
        record=_candidate_record(session),
        next_sequence=4,
        command=MemoryReviewCommand(
            action=MemoryReviewAction.CONFIRM,
            operator="system:auto-promotion",
            reason="reconstructed from typed local evidence",
            actor=EventActor.HARNESS,
        ),
    )

    assert result.event.actor is EventActor.HARNESS


def test_memory_review_service_expires_candidate_memory() -> None:
    session = _completed_session()

    result = MemoryReviewService().review(
        session=session,
        record=_candidate_record(session),
        next_sequence=4,
        command=MemoryReviewCommand(
            action=MemoryReviewAction.EXPIRE,
            operator="bob",
            reason="stale workflow",
        ),
    )

    assert result.record.status is MemoryStatus.EXPIRED
    assert result.event.payload["status"] == "expired"
    assert result.event.payload["superseded_memory_ids"] == []
    assert result.event.payload["duplicate_of_memory_id"] is None


def test_memory_review_service_supersedes_prior_confirmed_memory_on_confirm() -> None:
    session = _completed_session()
    reviewed_at = datetime(2026, 7, 2, 11, 1, tzinfo=UTC)
    record = _candidate_record(session)
    prior = _candidate_record(session).model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000122")),
            "text": "run uv run pytest before push",
            "status": MemoryStatus.CONFIRMED,
        }
    )

    result = MemoryReviewService().review(
        session=session,
        record=record,
        next_sequence=4,
        command=MemoryReviewCommand(
            action=MemoryReviewAction.CONFIRM,
            operator="alice",
            reason="newer procedure",
            created_at=reviewed_at,
        ),
        existing_records=(prior,),
    )

    assert result.record.status is MemoryStatus.CONFIRMED
    assert len(result.superseded_records) == 1
    assert result.superseded_records[0].status is MemoryStatus.SUPERSEDED
    assert result.superseded_records[0].superseded_by == record.memory_id
    assert result.superseded_records[0].updated_at == reviewed_at
    assert result.event.payload["superseded_memory_ids"] == [str(prior.memory_id)]
    assert result.event.payload["duplicate_of_memory_id"] is None


def test_memory_review_service_keeps_prior_preferences_when_confirming_preference() -> None:
    session = _completed_session()
    reviewed_at = datetime(2026, 7, 2, 11, 1, tzinfo=UTC)
    record = _candidate_record(session).model_copy(
        update={
            "memory_type": MemoryType.PREFERENCE,
            "text": "Prefer concise CLI output.",
        }
    )
    prior = _candidate_record(session).model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000123")),
            "memory_type": MemoryType.PREFERENCE,
            "text": "Prefer focused test runs first.",
            "status": MemoryStatus.CONFIRMED,
        }
    )

    result = MemoryReviewService().review(
        session=session,
        record=record,
        next_sequence=4,
        command=MemoryReviewCommand(
            action=MemoryReviewAction.CONFIRM,
            operator="alice",
            reason="captured explicit preference",
            created_at=reviewed_at,
        ),
        existing_records=(prior,),
    )

    assert result.record.status is MemoryStatus.CONFIRMED
    assert result.superseded_records == ()
    assert result.event.payload["superseded_memory_ids"] == []
    assert result.event.payload["duplicate_of_memory_id"] is None


def test_memory_review_service_expires_duplicate_confirm_against_existing_confirmed() -> None:
    session = _completed_session()
    reviewed_at = datetime(2026, 7, 2, 11, 1, tzinfo=UTC)
    record = _candidate_record(session)
    prior = _candidate_record(session).model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000124")),
            "status": MemoryStatus.CONFIRMED,
            "text": "run   make check before push",
        }
    )

    result = MemoryReviewService().review(
        session=session,
        record=record,
        next_sequence=4,
        command=MemoryReviewCommand(
            action=MemoryReviewAction.CONFIRM,
            operator="alice",
            reason="duplicate verified command",
            created_at=reviewed_at,
        ),
        existing_records=(prior,),
    )

    assert result.record.status is MemoryStatus.EXPIRED
    assert result.superseded_records == ()
    assert result.duplicate_of is not None
    assert result.duplicate_of.memory_id == prior.memory_id
    assert result.event.payload["status"] == "expired"
    assert result.event.payload["duplicate_of_memory_id"] == str(prior.memory_id)


def test_memory_review_service_rejects_non_candidate_memory() -> None:
    session = _completed_session()
    record = _candidate_record(session).model_copy(update={"status": MemoryStatus.CONFIRMED})

    with pytest.raises(ValueError, match="candidate memory"):
        MemoryReviewService().review(
            session=session,
            record=record,
            next_sequence=4,
            command=MemoryReviewCommand(
                action=MemoryReviewAction.CONFIRM,
                operator="alice",
                reason="already checked",
            ),
        )


def test_memory_review_service_rejects_memory_from_another_session() -> None:
    session = _completed_session()
    other_session = Session.create(title="other").model_copy(
        update={"status": SessionStatus.COMPLETED}
    )
    record = _candidate_record(other_session)

    with pytest.raises(ValueError, match="source session"):
        MemoryReviewService().review(
            session=session,
            record=record,
            next_sequence=4,
            command=MemoryReviewCommand(
                action=MemoryReviewAction.CONFIRM,
                operator="alice",
                reason="wrong scope",
            ),
        )


def _completed_session() -> Session:
    created_at = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    return Session.create(title="memory review", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.COMPLETED,
            "current_sequence": 3,
            "updated_at": created_at,
        }
    )


def _candidate_record(session: Session) -> MemoryRecord:
    created_at = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000121")),
        memory_type=MemoryType.PROCEDURE,
        text="run make check before push",
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id="/tmp/repo",
        source_session_id=session.session_id,
        source_event_start=2,
        source_event_end=2,
        created_at=created_at,
        updated_at=created_at,
    )
