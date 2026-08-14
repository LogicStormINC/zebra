"""Wave 5 Phase 1 red-first tests (ZNX-WAVE5-OUTER-ATTEMPTS-01, Gate 1).

These tests MUST FAIL on the synchronized Gate 0 base (6afbafa + Gate 0
commits) and MUST PASS after Phase 1 implements generic outer attempt
coordination. They pin: in-run Attempt 1 -> Attempt 2 under one Stable Task,
durable attempt start/outcome coordinates separate from Task terminal,
crash-after-outcome recovery, pre-dispatch reconstruction fail-closed
(W5-DSH-01), dispatch/usage linkage to stable attempt identity, and frozen
policy caps.
"""

from pathlib import Path

import pytest
from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _created_at,
    _tool_gateway,
)
from zebra_agent_worker import SessionRecoveryService


def _seed(
    database_path: Path,
    workspace_root: Path,
    *,
    max_attempts: int = 2,
):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued worker task",
            user_input="Continue the queued task.",
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=max_attempts,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    return bootstrap


class _ExplodingGateway:
    def complete(self, messages, *, tools=()):
        raise RuntimeError("provider transport exploded")

    def complete_stream(self, messages, *, tools=(), on_text_delta=None):
        raise RuntimeError("provider transport exploded")


class _RejectingGateway:
    def complete(self, messages, *, tools=()):
        raise ModelResponseRejectedError(
            "provider rejected the response",
            phase="validate",
            retryable=False,
        )

    def complete_stream(self, messages, *, tools=(), on_text_delta=None):
        raise ModelResponseRejectedError(
            "provider rejected the response",
            phase="validate",
            retryable=False,
        )


def _attempt_started_events(events):
    return [event for event in events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED]


def _attempt_outcome_events(events):
    return [event for event in events if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED]


# P1-1: a retryable attempt-1 failure must run Attempt 2 inside the same
# execute_session, with continuous sequences and durable coordinates.
def test_p1_1_retryable_failure_runs_attempt_2_in_one_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase1-p1.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="phase1-red-p1",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    started = _attempt_started_events(events)
    outcomes = _attempt_outcome_events(events)
    failed = [event for event in events if event.event_type is EventType.SESSION_FAILED]
    assert [event.payload["attempt_sequence"] for event in started] == [1, 2]
    assert [event.payload["attempt_id"] for event in started] == [
        "attempt-1",
        "attempt-2",
    ]
    assert started[1].payload["causal_attempt_id"] == "attempt-1"
    assert len(outcomes) == 2
    assert [event.payload["attempt_id"] for event in outcomes] == [
        "attempt-1",
        "attempt-2",
    ]
    for outcome in outcomes:
        assert outcome.payload["ended_at"] is not None
        assert outcome.payload["terminal_reason"]
    assert len(failed) == 1
    assert failed[0].payload["attempt_number"] == 2


# P1-2: an accepted attempt terminalizes once without starting Attempt 2.
def test_p1_2_accepted_attempt_terminates_without_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase1-p2.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="phase1-red-p2",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    started = _attempt_started_events(events)
    completed = [event for event in events if event.event_type is EventType.SESSION_COMPLETED]
    assert [event.payload["attempt_sequence"] for event in started] == [1]
    assert len(completed) == 1
    assert completed[0].payload["attempt_number"] == 1


# P1-3: non-retriable failures must never start Attempt 2.
def test_p1_3_non_retriable_failure_does_not_start_attempt_2(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase1-p3.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _RejectingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="phase1-red-p3",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    started = _attempt_started_events(events)
    assert [event.payload["attempt_sequence"] for event in started] == [1]
    assert [event.payload["terminal_reason"] for event in _attempt_outcome_events(events)] == [
        "model_response_rejected"
    ]


# P1-4: crash after a retriable outcome must resume with Attempt 2 exactly
# once - no attempt-1 replay, no duplicate start, no skipped sequence.
def test_p1_4_crash_after_outcome_resumes_with_attempt_2(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase1-p4.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    event_store = SQLiteEventStore(database_path)
    durable = (
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
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
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
            },
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in durable:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="phase1-red-p4",
        executed_at=_created_at(),
    )

    events = event_store.list_for_session(session_id)
    started = _attempt_started_events(events)
    assert [event.payload["attempt_sequence"] for event in started] == [1, 2]
    assert len(_attempt_outcome_events(events)) == 2


# P1-5 (W5-DSH-01): an inconsistent durable reconstruction (Attempt 2 started
# without a prior Attempt-1 outcome) must fail closed BEFORE the gateway is
# called.
def test_p1_5_reconstruction_mismatch_fails_closed_before_gateway(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase1-p5.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    event_store = SQLiteEventStore(database_path)
    inconsistent = SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 2},
        created_at=_created_at(),
    )
    event_store.append(inconsistent)
    SQLiteProjectionStore(database_path).save_session(apply_event(bootstrap.session, inconsistent))
    calls: list[str] = []

    class _RecordingGateway:
        def complete(self, messages, *, tools=()):
            calls.append("complete")
            return None

        def complete_stream(self, messages, *, tools=(), on_text_delta=None):
            calls.append("complete_stream")
            return None

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _RecordingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="phase1-red-p5",
        executed_at=_created_at(),
    )

    assert calls == []
    events = event_store.list_for_session(session_id)
    outcomes = _attempt_outcome_events(events)
    assert outcomes
    assert outcomes[-1].payload["terminal_reason"] == "attempt_reconstruction_invalid"


# P1-6: every dispatch/usage event links to the stable attempt identity.
def test_p1_6_dispatch_events_carry_stable_attempt_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase1-p6.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=1)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _tool_gateway(settings=settings),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="phase1-red-p6",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    started = _attempt_started_events(events)
    attempt_ids = {event.payload["attempt_id"] for event in started}
    assert attempt_ids == {"attempt-1"}
    for event in events:
        if event.event_type in {
            EventType.MODEL_REQUEST_STARTED,
            EventType.MODEL_RESPONSE_RECEIVED,
        }:
            assert event.payload["attempt_id"] == "attempt-1"
            assert event.payload["stable_task_id"]


# P1-7: policy caps are frozen at creation; an over-cap task fails closed.
def test_p1_7_over_cap_policy_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "phase1-p7.db"
    with pytest.raises(ValueError):
        _seed(database_path, tmp_path, max_attempts=3)
    with pytest.raises(ValueError):
        SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="Over-cap corrections",
                user_input="continue",
                workspace_root=tmp_path.resolve(),
                max_attempts=2,
                max_corrections_per_attempt=2,
            )
        )


# P1-8: crash between a non-retriable/exhausted outcome and the Task terminal
# must re-commit the terminal exactly once without any dispatch.
def test_p1_8_crash_after_non_retriable_outcome_recommits_terminal_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "phase1-p8.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    event_store = SQLiteEventStore(database_path)
    durable = (
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
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.ATTEMPT_OUTCOME_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "outcome": "failed",
                "ended_at": _created_at().isoformat(),
                "terminal_reason": "model_response_rejected",
                "retry_scheduled": False,
                "next_attempt_sequence": None,
            },
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in durable:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    calls: list[str] = []

    class _RecordingGateway:
        def complete(self, messages, *, tools=()):
            calls.append("complete")
            return None

        def complete_stream(self, messages, *, tools=(), on_text_delta=None):
            calls.append("complete_stream")
            return None

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _RecordingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="phase1-red-p8",
        executed_at=_created_at(),
    )

    assert calls == []
    events = event_store.list_for_session(session_id)
    failed = [event for event in events if event.event_type is EventType.SESSION_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["attempt_number"] == 1
    assert len(_attempt_started_events(events)) == 1
    assert len(_attempt_outcome_events(events)) == 1
