"""Native PostgreSQL progress transactions in a disposable test database."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from threading import Barrier, local

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


@pytest.mark.parametrize("initialized", [False, True])
def test_postgres_concurrent_frontier_has_one_winner(native_progress_dsn, monkeypatch, initialized):
    tasks, events, scope = seed(native_progress_dsn)
    page = tasks.read_event_page(scope.task_id, 0)
    if initialized:
        head = tasks.advance_worker_progress(scope, page)
        append(events, scope, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
        page = tasks.read_event_page(scope.task_id, head.through_sequence)
    barrier, thread, arrivals = Barrier(2), local(), []
    read = tasks._progress_head

    def racing_read(connection, scope, **kwargs):
        if getattr(thread, "arrived", False):
            return read(connection, scope, **kwargs)
        thread.arrived = True
        assert kwargs.get("lock"), "advancement must lock the bounded head read"
        if initialized:
            arrivals.append("existing")
            barrier.wait(timeout=1)
        try:
            return read(connection, scope, **kwargs)
        except CheckpointNotReady:
            arrivals.append("missing")
            barrier.wait(timeout=1)  # Both observe missing before either INSERT.
            raise

    monkeypatch.setattr(tasks, "_progress_head", racing_read)

    def advance(_):
        try:
            return tasks.advance_worker_progress(scope, page).through_sequence
        except CheckpointStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(advance, range(2)), key=str) == [page.next_sequence, "stale"]
    assert arrivals == ["existing" if initialized else "missing"] * 2
    monkeypatch.setattr(tasks, "_progress_head", read)
    assert tasks.read_worker_progress(scope).through_sequence == page.next_sequence


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


@pytest.mark.parametrize("composition", ["native", "foreign", "custom"])
def test_checked_progress_header_shares_only_native_same_scope(
    native_progress_dsn, monkeypatch, composition,
):
    from datetime import timedelta

    from agent_storage import PostgresLeaseStore
    from agent_storage.postgres.database import PostgresDatabase
    from zebra_agent_worker.progress_recovery import WorkerProgressRecovery
    from zebra_agent_worker.worker_budget import BudgetExecutionCheck

    from tests.stream_storage.telemetry import Telemetry, phase

    tasks, _, scope = seed(native_progress_dsn)
    page = tasks.read_event_page(scope.task_id, 0, limit=256, max_bytes=1_048_576)
    head = tasks.advance_worker_progress(scope, page)
    leases = PostgresLeaseStore(native_progress_dsn, deployment_namespace=NS)
    lease = leases.acquire(
        scope.task_id, owner_instance_id="header-check", ttl=timedelta(seconds=60),
    )

    def owned():
        assert leases.get(lease.session_id).fence == lease.fence

    database = leases._database if composition != "foreign" else PostgresDatabase(
        native_progress_dsn, deployment_namespace="foreign-header-scope",
    )
    if composition == "custom":
        original = tasks.read_latest_run_header
        monkeypatch.setattr(tasks, "read_latest_run_header", lambda task: original(task))
    check = BudgetExecutionCheck(owned, ownership_database=database)
    recovered = WorkerProgressRecovery(tasks, head, check, 8)
    telemetry = Telemetry()
    with telemetry.installed(), phase("header"):
        assert recovered.catch_up() is None
    assert telemetry.calls["initial/header/client_commit"] == (
        1 if composition == "native" else 2
    )


def test_checked_progress_header_sees_new_run_and_clears_read_scope(native_progress_dsn):
    from agent_storage.postgres.work_unit import borrow_work_unit
    from zebra_agent_worker.execution_events import ExecutionInterrupted
    from zebra_agent_worker.progress_recovery import WorkerProgressRecovery
    from zebra_agent_worker.worker_budget import BudgetExecutionCheck

    tasks, events, scope = seed(native_progress_dsn)
    page = tasks.read_event_page(scope.task_id, 0, limit=256, max_bytes=1_048_576)
    head = tasks.advance_worker_progress(scope, page)
    command = SessionCommand(
        session_id=scope.task_id, kind=SessionCommandKind.RUN,
        expected_revision=1, idempotency_key="checked-header-new-run",
        payload={"run_id": "replacement"},
    )

    def changed():
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                append, events, scope, EventType.SESSION_COMMAND_ACCEPTED, command.event_payload(),
            ).result()

    check = BudgetExecutionCheck(changed, ownership_database=tasks._database)
    recovery = WorkerProgressRecovery(tasks, head, check, 8)
    with pytest.raises(ExecutionInterrupted, match="superseded"):
        recovery.catch_up()
    assert borrow_work_unit((tasks._database._dsn, NS)) is None
    assert tasks.read_latest_run_header(scope.task_id).run_id == "replacement"


def test_checked_progress_header_closes_before_page_advance(native_progress_dsn, monkeypatch):
    from agent_core.ports.worker_progress import WorkerProgressHead, WorkerProgressState
    from agent_storage.postgres.work_unit import borrow_work_unit
    from zebra_agent_worker.progress_recovery import WorkerProgressRecovery
    from zebra_agent_worker.worker_budget import BudgetExecutionCheck

    tasks, _, scope = seed(native_progress_dsn)
    head = WorkerProgressHead(scope, scope.anchor_sequence - 1, None, WorkerProgressState())
    check = BudgetExecutionCheck(lambda: None, ownership_database=tasks._database)
    advance = tasks.advance_worker_progress
    writes = []

    def independently_committed(*args, **kwargs):
        assert borrow_work_unit((tasks._database._dsn, NS)) is None
        writes.append(1)
        return advance(*args, **kwargs)

    monkeypatch.setattr(tasks, "advance_worker_progress", independently_committed)
    recovery = WorkerProgressRecovery(tasks, head, check, 8)
    recovery.catch_up()
    assert writes == [1]
    assert tasks.read_worker_progress(scope) == recovery.head



def test_checked_progress_header_refuses_writes_inside_read_phase(native_progress_dsn):
    import psycopg
    from agent_storage.postgres.work_unit import borrow_work_unit

    tasks, _, scope = seed(native_progress_dsn)

    def write():
        with tasks._database.connect() as connection:
            connection.execute(
                "UPDATE agent_tasks SET active_segment_id=active_segment_id "
                "WHERE deployment_namespace=%s AND task_id=%s", (NS, scope.task_id),
            )

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        tasks.read_latest_run_header(scope.task_id, ownership_check=write)
    assert borrow_work_unit((tasks._database._dsn, NS)) is None
