"""Wave 5 Gate 1 frozen-policy and recovery edge cases."""

from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.agent_tasks import TaskEvent
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from wave5_gate1_corrections_support import (
    _attempt_started,
    _ExplodingGateway,
    _outcomes,
    _RecordingGateway,
    _seed,
)
from worker_execution_support import _build_execution_service, _created_at
from zebra_agent_worker.task_recovery import task_frozen_facts


def test_c15_later_child_cannot_expand_root_frozen_none_fields() -> None:
    session_id = SessionId(uuid4())
    task_id = TaskId(uuid4())
    root = SessionEvent(
        event_id=EventId(uuid4()),
        session_id=session_id,
        sequence=2,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={"title": "root", "user_input": "continue", "max_attempts": 2},
        created_at=_created_at(),
    )
    child = SessionEvent(
        event_id=EventId(uuid4()),
        session_id=session_id,
        sequence=20,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "child",
            "user_input": "continue",
            "execution_profile_id": "expanded",
            "max_model_calls": 3,
        },
        created_at=_created_at(),
    )

    def task_event(sequence: int, event: SessionEvent) -> TaskEvent:
        return TaskEvent(
            task_id=task_id,
            task_sequence=sequence,
            segment_id=session_id,
            segment_sequence=sequence,
            event=event,
        )

    with pytest.raises(ValueError, match="drift"):
        task_frozen_facts((task_event(2, root), task_event(20, child)))
    facts = task_frozen_facts((task_event(2, root),))
    assert facts.policy.max_attempts == 2
    assert facts.policy.execution_profile_id is None
    assert facts.max_model_calls is None


def test_c16_guarded_dispatch_after_durable_compaction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c16.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    additions = (
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "started_at": _created_at().isoformat(),
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.CONTEXT_COMPACTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "before_tokens": 500,
                "after_tokens": 100,
                "removed_message_count": 2,
                "retained_message_count": 2,
                "within_budget": True,
                "provenance": "test_compaction",
            },
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in additions:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    from worker_execution_support import _assistant_only_gateway

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="corrections-red-c16",
        executed_at=_created_at(),
    )
    events = event_store.list_for_session(session_id)
    assert any(event.event_type is EventType.MODEL_REQUEST_STARTED for event in events)
    assert sum(event.event_type is EventType.SESSION_COMPLETED for event in events) == 1


def test_c17_crash_before_provider_response_fails_closed_without_redispatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c17.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    additions = (
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "started_at": _created_at().isoformat(),
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.MODEL_REQUEST_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "model_call_id": "call-in-flight",
            },
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in additions:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    gateway = _RecordingGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="corrections-red-c17",
        executed_at=_created_at(),
    )
    assert gateway.calls == []
    failed = [
        event
        for event in event_store.list_for_session(session_id)
        if event.event_type is EventType.SESSION_FAILED
    ]
    assert len(failed) == 1
    assert failed[0].payload["metadata"]["stop_reason"] == "attempt_reconstruction_invalid"


def test_c18_correlated_model_step_resumes_attempt_2(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c18.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    additions = (
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "started_at": _created_at().isoformat(),
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.MODEL_REQUEST_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "model_call_id": "call-1",
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=5,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "model_call_id": "call-1",
                "assistant_message": "attempt-1 response",
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=6,
            event_type=EventType.ATTEMPT_OUTCOME_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "outcome": "failed",
                "ended_at": _created_at().isoformat(),
                "terminal_reason": "model_execution_failed",
                "retry_scheduled": True,
                "next_attempt_sequence": 2,
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
                "result_metadata": {"model_calls_used": 1, "tool_calls_executed": 0},
            },
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in additions:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="corrections-red-c18",
        executed_at=_created_at(),
    )
    events = event_store.list_for_session(session_id)
    assert [event.payload["attempt_sequence"] for event in _attempt_started(events)] == [1, 2]
    assert not any(
        event.payload.get("terminal_reason") == "attempt_reconstruction_invalid"
        for event in _outcomes(events)
    )
