"""Native PostgreSQL progress transactions in a disposable test database."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.harness.public_output import PublicOutputPolicy
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
)
from agent_core.ports.worker_progress import WorkerProgressScope
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    bootstrap_control_plane_epoch,
)

from tests.agent_storage import test_postgres_task_projection_checkpoints as checkpoint_tests
from tests.agent_storage.test_worker_progress import output_payload

NS = "native-worker-progress"
native_progress_dsn = checkpoint_tests.checkpoint_dsn


def seed(dsn):
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NS)
    session = new_session_id()
    events = PostgresEventStore(dsn, deployment_namespace=NS)
    first = SessionEvent.create(
        session_id=session,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Native progress"},
    )
    events.append(first)
    PostgresProjectionStore(dsn, deployment_namespace=NS).save_session(rebuild_session([first]))
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=NS)
    task = tasks.ensure_for_session(session)
    while not tasks.backfill_event_positions(task.task_id):
        pass
    while not tasks.backfill_replay_headers(task.task_id):
        pass
    command = SessionCommand(
        session_id=session,
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key="native-progress",
        payload={"run_id": "opaque-host-run"},
    )
    anchor = SessionEvent.create(
        session_id=session,
        sequence=1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )
    events.append(anchor)
    return (
        tasks,
        events,
        WorkerProgressScope(NS, task.task_id, "opaque-host-run", anchor.event_id, 1),
    )


def append(events, scope, kind, payload):
    events.append(
        SessionEvent.create(
            session_id=scope.task_id,
            sequence=len(events.list_for_session(scope.task_id)),
            event_type=kind,
            actor=EventActor.HARNESS,
            payload=payload,
        )
    )


def test_postgres_restores_attempt_policy_budget_and_indexed_membership(
    native_progress_dsn, monkeypatch
):
    tasks, events, scope = seed(native_progress_dsn)
    with pytest.raises(CheckpointNotReady):
        tasks.read_worker_progress(scope)
    policy = PublicOutputPolicy(version="frozen-native")
    append(events, scope, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 3})
    append(
        events,
        scope,
        EventType.MODEL_REQUEST_STARTED,
        {
            "attempt_number": 3,
            "purpose": "public_expression",
            "public_output_policy": asdict(policy),
        },
    )
    append(events, scope, EventType.PUBLIC_OUTPUT, output_payload(attempt=3))
    monkeypatch.setattr(events, "list_for_session", lambda _: pytest.fail("unbounded history read"))
    page = tasks.read_event_page(scope.task_id, 0, limit=256, max_bytes=1_048_576)
    head = tasks.advance_worker_progress(scope, page)
    reopened = PostgresAgentTaskStore(native_progress_dsn, deployment_namespace=NS)
    assert reopened.read_worker_progress(scope) == head
    assert head.state.attempt_number == 3 and head.state.expression_calls_used == 1
    assert head.state.published_count == 1 and head.state.result_published
    assert reopened.worker_output_published(scope, "public:2:found")
    assert reopened.worker_receipts_covered(scope, ("read:1", "unknown")) == frozenset({"read:1"})


def test_postgres_concurrent_frontier_has_one_winner(native_progress_dsn):
    tasks, _, scope = seed(native_progress_dsn)
    page = tasks.read_event_page(scope.task_id, 0)

    def advance(_):
        try:
            return tasks.advance_worker_progress(scope, page).through_sequence
        except CheckpointStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(advance, range(2)), key=str) == [1, "stale"]
    assert tasks.read_worker_progress(scope).through_sequence == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace", "foreign"),
        ("run_id", "forged"),
        ("version", "unknown"),
        ("anchor_sequence", 0),
    ],
)
def test_postgres_rejects_foreign_progress_identity(native_progress_dsn, field, value):
    tasks, _, scope = seed(native_progress_dsn)
    with pytest.raises(CheckpointConflict):
        tasks.advance_worker_progress(
            replace(scope, **{field: value}), tasks.read_event_page(scope.task_id, 0)
        )
    with pytest.raises(CheckpointNotReady):
        tasks.read_worker_progress(scope)


def test_postgres_forged_payload_or_old_attempt_cannot_advance_head(native_progress_dsn):
    tasks, events, scope = seed(native_progress_dsn)
    append(events, scope, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 3})
    append(events, scope, EventType.PUBLIC_OUTPUT, output_payload(attempt=3))
    page = tasks.read_event_page(scope.task_id, 0)
    entries = list(page.events)
    entries[-1] = replace(
        entries[-1],
        event=entries[-1].event.model_copy(
            update={"payload": output_payload(attempt=3, content="forged")}
        ),
    )
    with pytest.raises(CheckpointConflict, match="canonical"):
        tasks.advance_worker_progress(scope, replace(page, events=tuple(entries)))
    with pytest.raises(CheckpointNotReady):
        tasks.read_worker_progress(scope)
    committed = tasks.advance_worker_progress(scope, page)
    append(
        events,
        scope,
        EventType.MODEL_RESPONSE_DELTA,
        {"attempt_number": 1, "model_call_id": "old", "delta_index": 0, "content_delta": "Stale"},
    )
    with pytest.raises(CheckpointConflict, match="Attempt"):
        tasks.advance_worker_progress(
            scope, tasks.read_event_page(scope.task_id, page.next_sequence)
        )
    assert tasks.read_worker_progress(scope) == committed
