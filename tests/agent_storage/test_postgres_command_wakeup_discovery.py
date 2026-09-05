"""Operator-only history backfill and scope-keyed candidate discovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.contracts.broker_envelope import PrincipalScope
from agent_storage.postgres.command_wakeup import CommandAdmissionCapacityError
from agent_storage.postgres.command_wakeup_discovery import (
    PendingCursor,
    backfill_command_batch,
    begin_command_backfill,
    discover_pending_commands,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import (
    NAMESPACE,
    _counts,
    _enable,
    _seed,
    _store,
)
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_dsn_fixture

dsn = _dsn_fixture
postgres_dsn = _postgres_dsn_fixture
SCOPE = PrincipalScope(kind="principal", tenant_id="tenant-a", workspace_id="workspace-a")


def _begin(dsn):
    return begin_command_backfill(dsn, deployment_namespace=NAMESPACE)


def _batch(dsn, size=2):
    return backfill_command_batch(dsn, deployment_namespace=NAMESPACE, batch_size=size)


def _discover(dsn, **kwargs):
    return discover_pending_commands(dsn, deployment_namespace=NAMESPACE, scope=SCOPE, **kwargs)


@pytest.mark.parametrize("limit", [True, False, 0, -1, 501, 1.0, "2", None])
def test_bounds_rejected_before_connection(limit):
    with pytest.raises(ValueError, match="batch size"):
        backfill_command_batch("not a DSN", deployment_namespace=NAMESPACE, batch_size=limit)
    with pytest.raises(ValueError, match="batch size"):
        discover_pending_commands(
            "not a DSN", deployment_namespace=NAMESPACE, scope=SCOPE, batch_size=limit
        )


@pytest.mark.parametrize(
    "timestamp,identity",
    [
        (datetime(2026, 1, 1), uuid4()),
        ("invalid", uuid4()),
        (datetime.now(UTC), "not-a-uuid"),
    ],
)
def test_cursor_validation(timestamp, identity):
    with pytest.raises(ValueError, match="cursor"):
        PendingCursor(timestamp, identity)


@pytest.mark.parametrize("namespace", ["x" * 129, "bad\nnamespace", "bad\x7f", "", " "])
def test_namespace_contract_rejected_before_cutover_connection(namespace):
    with pytest.raises(ValueError, match="namespace"):
        begin_command_backfill("not a DSN", deployment_namespace=namespace)


def test_empty_explicit_cutover_and_idempotent_completion(dsn):
    assert _discover(dsn) == ()
    with pytest.raises(ValueError, match="explicit"):
        _batch(dsn)
    progress = _begin(dsn)
    assert progress.state == "complete" and progress.high_session_id is None
    assert _begin(dsn) == _batch(dsn) == progress
    assert _counts(dsn) == (0, 0)


def test_multiple_old_sessions_pages_timestamp_independence_and_live_behind_cursor(dsn):
    sessions = sorted((_seed(dsn) for _ in range(3)), key=lambda s: s.session_id)
    events = []
    for i, session in enumerate(sessions):
        for n in range(2):
            event = _command(session.session_id, sequence=3 + n, key=f"history-{i}-{n}")
            event = event.model_copy(
                update={"created_at": datetime(2001, 1, 1, tzinfo=UTC) + timedelta(days=1 - i)}
            )
            events.append(_store(dsn).append(event))
    progress = _begin(dsn)
    assert progress.high_session_id == sessions[-1].session_id
    assert _batch(dsn).cursor_session_id == sessions[0].session_id
    assert _batch(dsn).cursor_session_id == sessions[1].session_id
    live = _command(sessions[0].session_id, sequence=5, key="live-behind")
    _store(dsn).append(live)
    assert _counts(dsn) == (5, 5)
    progress = _batch(dsn)
    assert progress.state == "complete"
    assert _begin(dsn) == _batch(dsn) == progress
    assert _counts(dsn) == (7, 7)
    found, cursor = [], None
    while page := _discover(dsn, batch_size=2, after=cursor):
        found.extend(page)
        cursor = page[-1].cursor
    assert {row.cursor.accepted_event_id for row in found} == {
        event.event_id for event in [*events, live]
    }
    assert len(found) == 7


def test_invalid_scope_rolls_back_whole_batch_and_cursor(dsn):
    sessions = sorted((_seed(dsn) for _ in range(2)), key=lambda s: s.session_id)
    for session in sessions:
        _store(dsn).append(_command(session.session_id))
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_projections SET namespace_id = 'wrong' WHERE session_id = %s",
            (sessions[-1].session_id,),
        )
    before = _begin(dsn)
    with pytest.raises(ValueError, match="matching bounded Host scope"):
        _batch(dsn)
    assert _counts(dsn) == (0, 0)
    assert _begin(dsn) == before
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_projections SET namespace_id = 'tenant-a'")
    assert _batch(dsn).state == "complete"
    assert _counts(dsn) == (2, 2)


def test_backfill_respects_global_outbox_capacity_and_keeps_cursor_atomic(dsn):
    sessions = sorted((_seed(dsn) for _ in range(2)), key=lambda item: item.session_id)
    for index, session in enumerate(sessions):
        _store(dsn).append(_command(session.session_id, key=f"history-{index}"))
    before = _begin(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE command_wakeup_rollouts
               SET max_unpublished_outbox=1, reserved_control_outbox=0"""
        )
    with pytest.raises(CommandAdmissionCapacityError, match="command_outbox_capacity"):
        _batch(dsn)
    assert _counts(dsn) == (0, 0)
    assert _begin(dsn) == before


def test_existing_live_rollout_initializes_history_without_resetting_derived_status(dsn):
    session = _seed(dsn)
    _enable(dsn)
    _store(dsn).append(_command(session.session_id))
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET status = 'done'")
        connection.execute("UPDATE broker_outbox SET status = 'published'")
    assert _begin(dsn).state == "running"
    finished = _batch(dsn)
    assert finished.state == "complete"
    assert _begin(dsn) == finished
    assert _discover(dsn) == ()
    assert _counts(dsn) == (1, 1)
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT status FROM broker_outbox").fetchone() == ("published",)


def test_outbox_failure_rolls_back_pending_and_progress(dsn):
    session = _seed(dsn)
    _store(dsn).append(_command(session.session_id))
    before = _begin(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("ALTER TABLE broker_outbox ADD CONSTRAINT reject_test CHECK(FALSE)")
    with pytest.raises(psycopg.errors.CheckViolation):
        _batch(dsn)
    assert _begin(dsn) == before
    assert _counts(dsn) == (0, 0)
    with psycopg.connect(dsn) as connection:
        connection.execute("ALTER TABLE broker_outbox DROP CONSTRAINT reject_test")
    assert _batch(dsn).state == "complete"
    assert _counts(dsn) == (1, 1)


def test_operator_disables_admission_without_advancing_backfill(dsn):
    session = _seed(dsn)
    _store(dsn).append(_command(session.session_id))
    before = _begin(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_wakeup_rollouts SET admission_enabled = FALSE")
    with pytest.raises(ValueError, match="explicit active cutover"):
        _batch(dsn)
    assert _begin(dsn) == before
    assert _counts(dsn) == (0, 0)
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT admission_enabled FROM command_wakeup_rollouts"
        ).fetchone() == (False,)


def test_pending_scope_deployment_terminal_filters_and_equal_time_keyset(dsn):
    session = _seed(dsn)
    _begin(dsn)
    for n in range(4):
        _store(dsn).append(_command(session.session_id, sequence=3 + n, key=str(n)))
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET created_at = '2026-01-01 UTC'")
    first = _discover(dsn, batch_size=2)
    second = _discover(dsn, batch_size=2, after=first[-1].cursor)
    assert len({row.command_id for row in (*first, *second)}) == 4
    assert discover_pending_commands(dsn, deployment_namespace="other", scope=SCOPE) == ()
    for scope in [
        SCOPE.model_copy(update={"tenant_id": "other"}),
        SCOPE.model_copy(update={"workspace_id": "other"}),
    ]:
        assert discover_pending_commands(dsn, deployment_namespace=NAMESPACE, scope=scope) == ()
    with psycopg.connect(dsn) as connection:
        for row, status in zip((*first, *second), ("done", "cancelled", "dead"), strict=False):
            connection.execute(
                "UPDATE session_command_pending SET status = %s WHERE command_id = %s",
                (status, row.command_id),
            )
    assert len(_discover(dsn)) == 1
    assert isinstance(first[0].cursor.accepted_event_id, UUID)


def test_cutover_waits_for_inflight_insert_then_captures_it(dsn):
    session = _seed(dsn)
    event = _command(session.session_id)
    entered = Event()

    def begin():
        entered.set()
        return _begin(dsn)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as connection:
            append_event_in_transaction(connection, NAMESPACE, event)
            future = pool.submit(begin)
            assert entered.wait(2)
            # Barrier cannot complete while this transaction owns the INSERT lock.
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
        progress = future.result(timeout=5)
    assert progress.high_session_id == session.session_id
    assert progress.high_sequence == event.sequence
    assert _batch(dsn).state == "complete"
    assert _counts(dsn) == (1, 1)
