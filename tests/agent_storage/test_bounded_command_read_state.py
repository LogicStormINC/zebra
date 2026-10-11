"""Actual PG command/control hot paths consume exact bounded durable prefixes."""

import time
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import current_turn, project_turns
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.command_read_state import (
    finish_command_read_state,
    load_command_read_state,
    lock_command_source,
)
from agent_storage.postgres.command_wakeup_control import ControlStatus, handle_control_command
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus, handoff_command
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.task_io import TaskIoConnection
from psycopg.rows import dict_row
from zebra_agent_api import RouteAdapter

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as postgres_fixture
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_direct_control_api import _app, _request
from tests.agent_storage.test_postgres_runtime_instances import SCOPE as DIRECT_SCOPE

dsn = dsn_fixture
postgres_dsn = postgres_fixture
WORKSPACE = _binding("test").host_capability.host_context.workspace_ref


def history(dsn, count):
    session = _seed(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    bootstrap = _store(dsn).list_for_session(session.session_id)
    turn = current_turn(bootstrap)
    assert turn is not None
    statement = (
        "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
        "event_type,payload,actor,created_at) SELECT %s,md5(%s||n::text)::uuid,%s,n,"
        "CASE WHEN n=3 OR n%%20=1 THEN 'turn_completed' "
        "WHEN n%%20=0 THEN 'user_message_received' ELSE 'runtime_cleanup_failed' END,"
        "CASE WHEN n=3 THEN jsonb_build_object('turn_id',%s::text,'turn_index',0,"
        "'closes_segment',false) WHEN n%%20=1 THEN jsonb_build_object('turn_id',"
        "'history-'||(n-1)::text,'turn_index',n%%7,'closes_segment',false) "
        "WHEN n%%20=0 THEN jsonb_build_object('content','exact','origin','human',"
        "'turn_id','history-'||n::text,'turn_index',n%%7) ELSE '{}'::jsonb END,"
        "CASE WHEN n%%20=0 THEN 'user' ELSE 'system' END,%s "
        "FROM generate_series(%s::bigint,%s::bigint) n"
    )
    with psycopg.connect(dsn) as connection:
        for start in range(3, count, 256):
            end = min(start + 255, count - 1)
            connection.execute(
                statement,
                (
                    NAMESPACE,
                    str(session.session_id),
                    session.session_id,
                    turn.turn_id,
                    session.updated_at,
                    start,
                    end,
                ),
            )
            connection.execute("UPDATE session_streams SET current_version=%s", (end,))
            connection.commit()
    return session.session_id


def prepare(dsn, session):
    prefixes = []
    for _ in range(100):
        try:
            finish_command_read_state(dsn, deployment_namespace=NAMESPACE, session_id=session)
            return prefixes
        except PreparationAdvanced as advanced:
            assert not prefixes or advanced.through_sequence > prefixes[-1]
            prefixes.append(advanced.through_sequence)
    raise AssertionError("native preparation failed to finish durable prefixes")


def intent(dsn, session, sequence, kind):
    command = SessionCommand(
        session_id=session,
        kind=SessionCommandKind(kind),
        expected_revision=sequence - 1,
        idempotency_key=str(uuid4()),
        payload={"content": "next exact Turn"} if kind == "message" else {},
    )
    return _store(dsn).append(
        SessionEvent.create(
            session_id=session,
            sequence=sequence,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
            idempotency_key=command.idempotency_key,
        )
    )


def reject_history(monkeypatch):
    monkeypatch.setattr(
        PostgresEventStore, "list_for_session", Mock(side_effect=AssertionError("history"))
    )
    monkeypatch.setattr(
        PostgresEventStore, "read_since", Mock(side_effect=AssertionError("history tail"))
    )
    execute = TaskIoConnection.execute
    pages = []

    def bounded(connection, query, parameters=None, **kwargs):
        if (
            isinstance(query, str)
            and "FROM session_events" in query
            and "ORDER BY sequence" in query
        ):
            assert "LIMIT" in query, query
            if query.startswith("SELECT sequence,event_bytes_bound"):
                pages.append(parameters)
        return execute(connection, query, parameters, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", bounded)
    return pages


@pytest.mark.parametrize("count", [1_000, 10_000, 100_000])
def test_native_message_exact_count_and_control_snapshot_no_whole_history(dsn, monkeypatch, count):
    session = history(dsn, count)
    full = _store(dsn).list_for_session(session)
    prepare(dsn, session)
    with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect_task_io() as connection:
        highwater = lock_command_source(connection, NAMESPACE, session)
        state = load_command_read_state(connection, NAMESPACE, session, highwater)
    assert state.session == rebuild_session(full)
    assert state.workspace == rebuild_workspace(full)
    assert state.turns.human_turn_count == len(project_turns(full))
    assert len(state.turns.records) == 1
    _enable(dsn)
    message = intent(dsn, session, count, "message")
    pages = reject_history(monkeypatch)
    result = handoff_command(
        dsn,
        deployment_namespace=NAMESPACE,
        scope=SCOPE,
        accepted_event_id=message.event_id,
        owner_instance_id="bounded-worker",
        ttl=timedelta(seconds=30),
    )
    assert result.status is HandoffStatus.ACCEPTED
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        event = connection.execute(
            "SELECT payload FROM session_events WHERE sequence=%s", (count + 1,)
        ).fetchone()
        assert event["payload"]["turn_index"] == len(project_turns(full))
    cancel = intent(dsn, session, count + 2, "cancel")
    outcome = handle_control_command(
        dsn, deployment_namespace=NAMESPACE, scope=SCOPE, accepted_event_id=cancel.event_id
    )
    assert outcome.status is ControlStatus.CANCELLED
    assert all(request[-1] <= 256 for request in pages)
    assert len(pages) < 10  # Independent of 1k/10k/100k historical prefix.


def test_native_stale_prefix_is_typed_preparing_then_same_generation_finishes(dsn, monkeypatch):
    session = history(dsn, 600)
    _enable(dsn)
    cancel = intent(dsn, session, 600, "cancel")
    with psycopg.connect(dsn) as connection:
        generation = connection.execute(
            "SELECT current_generation FROM session_command_pending"
        ).fetchone()[0]
    execute = TaskIoConnection.execute

    def slow(connection, query, parameters=None, **kwargs):
        if isinstance(query, str) and query.startswith("SELECT sequence,event_bytes_bound"):
            execute(connection, "SELECT pg_sleep(1.1)")
        return execute(connection, query, parameters, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", slow)
    started = time.monotonic()
    outcome = handle_control_command(
        dsn, deployment_namespace=NAMESPACE, scope=SCOPE, accepted_event_id=cancel.event_id
    )
    assert time.monotonic() - started < 3
    assert outcome.status is ControlStatus.PREPARING
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        prefix = connection.execute("SELECT * FROM session_command_read_heads").fetchone()
        assert prefix["through_sequence"] == 255
        assert not connection.execute("SELECT * FROM command_control_receipts").fetchall()
        assert not connection.execute("SELECT * FROM broker_control_inbox").fetchall()
        pending = connection.execute("SELECT * FROM session_command_pending").fetchone()
        assert pending["status"] == "pending" and pending["current_generation"] == generation
    monkeypatch.setattr(TaskIoConnection, "execute", execute)
    outcome = handle_control_command(
        dsn, deployment_namespace=NAMESPACE, scope=SCOPE, accepted_event_id=cancel.event_id
    )
    assert outcome.status is ControlStatus.CANCELLED


@pytest.mark.parametrize("lane", ["control", "handoff", "direct"])
def test_native_command_phases_share_one_real_sql_deadline(dsn, monkeypatch, lane):
    session = history(dsn, 100)
    _enable(dsn)
    accepted = (
        None
        if lane == "direct"
        else intent(dsn, session, 100, "message" if lane == "handoff" else "cancel")
    )
    execute = TaskIoConnection.execute
    deadlines = set()
    phases = []

    def slow(connection, query, parameters=None, **kwargs):
        deadlines.add(connection.deadline)
        if isinstance(query, str) and query.startswith("SELECT sequence,event_bytes_bound"):
            if "preparation" not in phases:
                phases.append("preparation")
                execute(connection, "SELECT pg_sleep(1.1)")
        if isinstance(query, str) and query.startswith("SET LOCAL lock_timeout"):
            phases.append("mutation")
            execute(connection, "SELECT pg_sleep(1.1)")
        return execute(connection, query, parameters, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", slow)
    started = time.monotonic()
    with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
        if lane == "direct":
            PostgresDirectControl(dsn, deployment_namespace=NAMESPACE).cancel(
                session, scope=DIRECT_SCOPE, workspace_ref=WORKSPACE, operation_id=uuid4()
            )
        elif lane == "control":
            handle_control_command(
                dsn,
                deployment_namespace=NAMESPACE,
                scope=SCOPE,
                accepted_event_id=accepted.event_id,
            )
        else:
            handoff_command(
                dsn,
                deployment_namespace=NAMESPACE,
                scope=SCOPE,
                accepted_event_id=accepted.event_id,
                owner_instance_id="budget-owner",
                ttl=timedelta(seconds=30),
            )
    assert time.monotonic() - started < 2.8
    assert phases == ["preparation", "mutation"]
    assert len(deadlines) == 1
    monkeypatch.setattr(TaskIoConnection, "execute", execute)
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute("SELECT count(*) FROM command_control_receipts").fetchone()[0] == 0
        )
        assert (
            connection.execute("SELECT count(*) FROM direct_control_operations").fetchone()[0] == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM session_events WHERE event_type='session_cancelled'"
            ).fetchone()[0]
            == 0
        )


def test_native_direct_cancel_receipt_keeps_exact_workspace_after_later_tail(dsn, monkeypatch):
    session = history(dsn, 1_000)
    prepare(dsn, session)
    reject_history(monkeypatch)
    control = PostgresDirectControl(dsn, deployment_namespace=NAMESPACE)
    operation = uuid4()
    result = control.cancel(
        session, scope=DIRECT_SCOPE, workspace_ref=WORKSPACE, operation_id=operation
    )
    later = SessionEvent.create(
        session_id=session,
        sequence=result.event.sequence + 1,
        event_type=EventType.RUNTIME_CLEANUP_FAILED,
        actor=EventActor.SYSTEM,
        payload={"target": "runtime", "error_type": "later", "attempt_number": 1},
    )
    _store(dsn).append(later)
    replay = control.cancel(
        session, scope=DIRECT_SCOPE, workspace_ref=WORKSPACE, operation_id=operation
    )
    assert replay == result and replay.workspace.current_sequence == result.event.sequence


def test_native_wrong_scope_or_outbox_never_prepares_derived_state(dsn):
    session = history(dsn, 1000)
    _enable(dsn)
    cancel = intent(dsn, session, 1000, "cancel")
    with pytest.raises(ValueError):
        handle_control_command(
            dsn,
            deployment_namespace=NAMESPACE,
            scope=SCOPE.model_copy(update={"tenant_id": "foreign"}),
            accepted_event_id=cancel.event_id,
        )
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute("SELECT count(*) FROM session_command_read_heads").fetchone()[0] == 0
        )
        connection.execute("UPDATE broker_outbox SET envelope_digest=%s", ("f" * 64,))
    with pytest.raises(ValueError):
        handle_control_command(
            dsn, deployment_namespace=NAMESPACE, scope=SCOPE, accepted_event_id=cancel.event_id
        )
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute("SELECT count(*) FROM session_command_read_heads").fetchone()[0] == 0
        )


def test_native_host_cancel_preparing_retry_then_idempotent_success(dsn, monkeypatch):
    session = history(dsn, 600)
    adapter = RouteAdapter(_app(dsn))
    execute = TaskIoConnection.execute

    def slow(connection, query, parameters=None, **kwargs):
        if isinstance(query, str) and query.startswith("SELECT sequence,event_bytes_bound"):
            execute(connection, "SELECT pg_sleep(1.1)")
        return execute(connection, query, parameters, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", slow)
    started = time.monotonic()
    response = adapter.handle(_request(session, key="same-host-cancel"))
    assert time.monotonic() - started < 3
    assert response.status_code == 503
    assert response.body == {
        "task_id": str(session),
        "session_id": str(session),
        "status": "preparing",
        "reason": "command_read_state_preparing",
        "retryable": True,
        "retry_after_seconds": 1,
        "cancelled": False,
    }
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute("SELECT count(*) FROM direct_control_operations").fetchone()[0] == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM session_events WHERE event_type='session_cancelled'"
            ).fetchone()[0]
            == 0
        )
    monkeypatch.setattr(TaskIoConnection, "execute", execute)
    response = adapter.handle(_request(session, key="same-host-cancel"))
    assert response.status_code == 200 and response.body["cancelled"] is True
    assert adapter.handle(_request(session, key="same-host-cancel")) == response
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute("SELECT count(*) FROM direct_control_operations").fetchone()[0] == 1
        )
