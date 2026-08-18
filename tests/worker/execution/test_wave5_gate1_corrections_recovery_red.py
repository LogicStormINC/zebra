"""Wave 5 Gate 1 correction red tests, part B (rollover, policy inheritance, recovery)."""

from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.tool_profiles import ToolProfile
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from wave5_gate1_corrections_support import (
    _attempt_started,
    _ExplodingGateway,
    _outcomes,
    _RecordingGateway,
    _seed,
)
from worker_execution_support import _build_execution_service, _created_at
from zebra_agent_worker import SessionRecoveryService


# C8 (blocker 6): after an internal Segment rollover, attempt state must be
# reconstructed from the ordered Stable Task stream - no duplicate Attempt 1.
def test_c8_segment_rollover_does_not_reset_attempt_sequence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c8.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    root_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    additions = (
        SessionEvent.create(
            session_id=root_id,
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
            session_id=root_id,
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
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=5,
            event_type=EventType.SESSION_SUSPENDED,
            actor=EventActor.HARNESS,
            payload={"reason": "context_pressure"},
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in additions:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(root_id)
    from agent_core.domain.session_handoff import HandoffActorKind, HandoffReason
    from zebra_agent_api.session_handoff import SessionHandoffApi

    response = SessionHandoffApi(database_path).create(
        str(root_id),
        {
            "title": "Internal rollover",
            "objective": task.goal,
            "stage_prompt": "Continue the verified checkpoint.",
            "reason": HandoffReason.INTERNAL_CONTEXT_PRESSURE.value,
        },
        idempotency_key="c8-internal-rollover",
        principal_identity_hash="c8",
        actor_kind=HandoffActorKind.AUTOMATION,
    )
    assert response.status_code in {200, 201}
    active = task_store.get_task(task.task_id)
    assert active is not None
    child_id = active.active_segment_id
    assert child_id != root_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )
    _build_execution_service(database_path).execute_session(
        child_id,
        worker_id="corrections-red-c8",
        executed_at=_created_at(),
    )
    task_events = task_store.read_events(task.task_id, -1)
    started = [
        item.event
        for item in task_events
        if item.event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in started] == [1, 2]
    assert [event.payload["attempt_id"] for event in started] == [
        "attempt-1",
        "attempt-2",
    ]
    assert len(_outcomes([item.event for item in task_events])) == 2
    child_requests = [
        item.event
        for item in task_events
        if item.event.event_type is EventType.MODEL_REQUEST_STARTED
        and item.event.payload.get("attempt_number") == 2
    ]
    assert child_requests
    root_user = next(
        item.event
        for item in task_events
        if item.event.event_type is EventType.USER_MESSAGE_RECEIVED
        and item.event.payload.get("source") != "session_handoff"
    )
    assert child_requests[0].payload["turn_id"] == f"turn:{root_user.event_id}"


# C9 (blocker 7): a handoff child inherits the root's frozen attempt policy
# exactly - max_attempts=2 and an explicit empty retry set survive unchanged.
def test_c9_handoff_child_inherits_frozen_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c9.db"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Frozen policy",
            user_input="continue",
            workspace_root=tmp_path.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            retryable_stop_reasons=(),
        )
    )
    root_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(root_id)
    started = SessionEvent.create(
        session_id=root_id,
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
    )
    completed = SessionEvent.create(
        session_id=root_id,
        sequence=4,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "summary": "done"},
        created_at=_created_at(),
    )
    session = bootstrap.session
    for event in (started, completed):
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(root_id)
    from agent_core.domain.session_handoff import HandoffActorKind, HandoffReason
    from zebra_agent_api.session_handoff import SessionHandoffApi

    response = SessionHandoffApi(database_path).create(
        str(root_id),
        {
            "title": "Follow-up",
            "objective": task.goal,
            "stage_prompt": "Continue.",
            "reason": HandoffReason.INTERNAL_CONTEXT_PRESSURE.value,
        },
        idempotency_key="c9-handoff",
        principal_identity_hash="c9",
        actor_kind=HandoffActorKind.AUTOMATION,
    )
    assert response.status_code in {200, 201}
    active = task_store.get_task(task.task_id)
    assert active is not None
    child_id = active.active_segment_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )
    _build_execution_service(database_path).execute_session(
        child_id,
        worker_id="corrections-red-c9",
        executed_at=_created_at(),
    )
    task_events = task_store.read_events(task.task_id, -1)
    started = [
        item.event
        for item in task_events
        if item.event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in started] == [1]
    failed = [
        item.event for item in task_events if item.event.event_type is EventType.SESSION_FAILED
    ]
    assert len(failed) == 1
    assert failed[0].payload["attempt_number"] == 1


# C10 (blocker 8): a crash after a completed attempt outcome must re-commit
# SESSION_COMPLETED with the same attempt number - never SESSION_FAILED.
def test_c10_completed_outcome_recommits_completed_terminal_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c10.db"
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
            event_type=EventType.ATTEMPT_OUTCOME_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "outcome": "completed",
                "ended_at": _created_at().isoformat(),
                "terminal_reason": "completed",
                "retry_scheduled": False,
                "next_attempt_sequence": None,
                "summary": "accepted",
                "result_metadata": {"model_calls_used": 1, "tool_calls_executed": 0},
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
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
        worker_id="corrections-red-c10",
        executed_at=_created_at(),
    )
    assert gateway.calls == []
    events = event_store.list_for_session(session_id)
    completed = [event for event in events if event.event_type is EventType.SESSION_COMPLETED]
    failed = [event for event in events if event.event_type is EventType.SESSION_FAILED]
    assert len(completed) == 1
    assert len(failed) == 0
    assert completed[0].payload["attempt_number"] == 1


# C11 (blocker 9): frozen Task budgets are cumulative - a retryable failure
# must not start Attempt 2 when the Stable Task model-call budget is spent.
def test_c11_model_call_budget_exhaustion_blocks_attempt_2(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c11.db"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Budgeted task",
            user_input="continue",
            workspace_root=tmp_path.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            max_model_calls=1,
        )
    )
    session_id = bootstrap.session.session_id
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(session_id)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="corrections-red-c11",
        executed_at=_created_at(),
    )
    events = event_store.list_for_session(session_id)
    assert [event.payload["attempt_sequence"] for event in _attempt_started(events)] == [1]
    failed = [event for event in events if event.event_type is EventType.SESSION_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["attempt_number"] == 1


# C12 (blocker 9): a frozen non-retriable code can never be widened to
# retryable, even when configured at the creation boundary.
def test_c12_non_retriable_code_cannot_be_frozen_as_retryable(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="Drifted retry policy",
                user_input="continue",
                workspace_root=tmp_path.resolve(),
                max_attempts=2,
                retryable_stop_reasons=("budget_exhausted",),
            )
        )


# C13 (blocker 6 nuance, regression): a terminal follow-up is a new logical
# epoch - the predecessor's completed outcome must not drive the follow-up
# into terminal synthesis, and the child executes a fresh Attempt 1.
def test_c13_terminal_follow_up_starts_fresh_epoch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_core.domain.session_handoff import HandoffActorKind, HandoffReason
    from zebra_agent_api.session_handoff import SessionHandoffApi

    database_path = tmp_path / "corrections-c13.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    root_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    additions = (
        SessionEvent.create(
            session_id=root_id,
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
            session_id=root_id,
            sequence=4,
            event_type=EventType.ATTEMPT_OUTCOME_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "outcome": "completed",
                "ended_at": _created_at().isoformat(),
                "terminal_reason": "completed",
                "retry_scheduled": False,
                "next_attempt_sequence": None,
                "summary": "accepted",
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=5,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1, "summary": "done"},
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in additions:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(root_id)
    handoff = SessionHandoffApi(database_path).create(
        str(root_id),
        {
            "title": "Follow-up",
            "objective": task.goal,
            "stage_prompt": "Continue from the verified checkpoint.",
            "reason": HandoffReason.INTERNAL_TERMINAL_FOLLOW_UP.value,
        },
        idempotency_key="c13-terminal-follow-up",
        principal_identity_hash="c13",
        actor_kind=HandoffActorKind.AUTOMATION,
    )
    assert handoff.status_code in {200, 201}
    active = task_store.get_task(task.task_id)
    assert active is not None
    child_id = active.active_segment_id
    assert child_id != root_id
    from worker_execution_support import _assistant_only_gateway

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    _build_execution_service(database_path).execute_session(
        child_id,
        worker_id="corrections-red-c13",
        executed_at=_created_at(),
    )
    child_events = event_store.list_for_session(child_id)
    child_started = _attempt_started(child_events)
    assert [event.payload["attempt_sequence"] for event in child_started] == [1]
    completed = [event for event in child_events if event.event_type is EventType.SESSION_COMPLETED]
    failed = [event for event in child_events if event.event_type is EventType.SESSION_FAILED]
    assert len(completed) == 1
    assert len(failed) == 0


# C14 (budget authority across Segment): a handoff child cannot erase the
# root's frozen model-call budget; cumulative budget enforcement survives
# rollover.
def test_c14_handoff_child_inherits_frozen_model_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c14.db"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Frozen budget",
            user_input="continue",
            workspace_root=tmp_path.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            max_model_calls=1,
        )
    )
    root_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(root_id)
    started = SessionEvent.create(
        session_id=root_id,
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
    )
    completed = SessionEvent.create(
        session_id=root_id,
        sequence=4,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "summary": "done"},
        created_at=_created_at(),
    )
    session = bootstrap.session
    for event in (started, completed):
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(root_id)
    from agent_core.domain.session_handoff import HandoffActorKind, HandoffReason
    from zebra_agent_api.session_handoff import SessionHandoffApi

    response = SessionHandoffApi(database_path).create(
        str(root_id),
        {
            "title": "Follow-up",
            "objective": task.goal,
            "stage_prompt": "Continue.",
            "reason": HandoffReason.INTERNAL_CONTEXT_PRESSURE.value,
        },
        idempotency_key="c14-handoff",
        principal_identity_hash="c14",
        actor_kind=HandoffActorKind.AUTOMATION,
    )
    assert response.status_code in {200, 201}
    active = task_store.get_task(task.task_id)
    assert active is not None
    child_id = active.active_segment_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )
    _build_execution_service(database_path).execute_session(
        child_id,
        worker_id="corrections-red-c14",
        executed_at=_created_at(),
    )
    task_events = task_store.read_events(task.task_id, -1)
    started = [
        item.event
        for item in task_events
        if item.event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in started] == [1]
    failed = [
        item.event for item in task_events if item.event.event_type is EventType.SESSION_FAILED
    ]
    assert len(failed) == 1
    assert failed[0].payload["attempt_number"] == 1
