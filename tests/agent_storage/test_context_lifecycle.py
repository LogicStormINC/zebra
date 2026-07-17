from datetime import UTC, datetime

import pytest
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextSourceEventRange,
)
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_session_id
from agent_storage import (
    ActiveContextProjectionConflictError,
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
)


def test_capsule_artifact_event_and_active_projection_advance_atomically(tmp_path) -> None:
    database_path = tmp_path / "context.db"
    store = SQLiteContextLifecycleStore(database_path)
    session_id = new_session_id()
    capsule = _capsule("ctxcap-1", "a" * 64, 4)

    stored = store.persist_capsule_and_advance(
        session_id=session_id,
        capsule=capsule,
        validation_context=_validation(capsule),
        sequence=5,
        expected_active_capsule_id=None,
    )

    assert store.get_capsule("ctxcap-1") == stored
    assert store.get_active_capsule(session_id) == stored
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert [event.event_type for event in events] == [EventType.CONTEXT_CAPSULE_CREATED]
    assert events[0].payload["artifact_id"] == str(stored.artifact_id)

    retried = store.persist_capsule_and_advance(
        session_id=session_id,
        capsule=capsule,
        validation_context=_validation(capsule),
        sequence=5,
        expected_active_capsule_id=None,
    )
    assert retried == stored
    assert len(SQLiteEventStore(database_path).list_for_session(session_id)) == 1


def test_active_projection_compare_and_swap_rolls_back_new_artifact(tmp_path) -> None:
    database_path = tmp_path / "context.db"
    store = SQLiteContextLifecycleStore(database_path)
    session_id = new_session_id()
    first = _capsule("ctxcap-1", "a" * 64, 4)
    store.persist_capsule_and_advance(
        session_id=session_id,
        capsule=first,
        validation_context=_validation(first),
        sequence=5,
        expected_active_capsule_id=None,
    )
    stale = _capsule("ctxcap-stale", "b" * 64, 5)

    with pytest.raises(ActiveContextProjectionConflictError):
        store.persist_capsule_and_advance(
            session_id=session_id,
            capsule=stale,
            validation_context=_validation(stale),
            sequence=6,
            expected_active_capsule_id=None,
        )

    assert store.get_capsule("ctxcap-stale") is None
    assert store.get_active_capsule(session_id).capsule.capsule_id == "ctxcap-1"  # type: ignore[union-attr]


def _capsule(capsule_id: str, source_hash: str, end_sequence: int) -> ContextCapsule:
    return ContextCapsule(
        capsule_id=capsule_id,
        objective="Finish compaction",
        immediate_next="Continue",
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=end_sequence),
        source_hash=source_hash,
        confidence=1.0,
        created_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
    )


def _validation(capsule: ContextCapsule) -> ContextCapsuleValidationContext:
    assert capsule.source_event_range is not None
    return ContextCapsuleValidationContext(
        expected_source_hash=capsule.source_hash,
        expected_source_event_range=capsule.source_event_range,
    )
