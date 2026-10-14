"""Native deny-only preflight saves proof work without authorizing recovery."""

from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import command_wakeup_recovery as recovery
from agent_storage.postgres.database import PostgresDatabase

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_command_wakeup_recovery import _due, _rows
from tests.agent_storage.test_postgres_leases import _expire

dsn, postgres_dsn = _dsn, _pg


class PreparationReached(Exception):
    pass


def reject_preparation(*args, continuation=None):
    raise PreparationReached


def test_active_lease_defers_before_preparation_without_changing_evidence(dsn, monkeypatch):
    command = _prepare(dsn)
    _handoff(dsn, command)
    _due(dsn)
    pending = _rows(dsn, "session_command_pending")[0]
    tables = ("broker_outbox", "command_handoff_receipts", "command_recovery_attempts")
    original = {table: _rows(dsn, table) for table in tables}
    monkeypatch.setattr(recovery, "prepare_command_recovery", reject_preparation)
    result = recovery.recover_command_batch(dsn, deployment_namespace=NAMESPACE, scope=SCOPE)
    assert result == (
        recovery.CommandRecovery(command.event_id, 0, recovery.RecoveryStatus.DEFERRED),
    )
    after = _rows(dsn, "session_command_pending")[0]
    assert after["recovery_due_at"] > pending["recovery_due_at"]
    assert {k: v for k, v in after.items() if k != "recovery_due_at"} == {
        k: v for k, v in pending.items() if k != "recovery_due_at"
    }
    assert {table: _rows(dsn, table) for table in tables} == original
    assert recovery.recover_command_batch(dsn, deployment_namespace=NAMESPACE, scope=SCOPE) == ()


@pytest.mark.parametrize(
    "boundary",
    [
        "expired",
        "released",
        "old_epoch",
        "disabled",
        "historical",
        "future_due",
        "foreign_scope",
        "foreign_session",
        "foreign_namespace",
        "fenced",
    ],
)
def test_non_active_or_non_scoped_candidate_retains_full_preparation(dsn, monkeypatch, boundary):
    command = _prepare(dsn)
    handoff = _handoff(dsn, command)
    _due(dsn)
    with psycopg.connect(dsn) as conn:
        if boundary == "expired":
            _expire(dsn, NAMESPACE, command.session_id)
        elif boundary == "released":
            conn.execute("UPDATE worker_leases SET released_at=clock_timestamp()")
        elif boundary == "old_epoch":
            conn.execute("UPDATE control_plane_epochs SET epoch=%s", (uuid4(),))
        elif boundary == "disabled":
            conn.execute("UPDATE command_wakeup_rollouts SET admission_enabled=false")
        elif boundary == "historical":
            conn.execute("UPDATE session_command_pending SET origin='historical'")
        elif boundary == "future_due":
            conn.execute(
                "UPDATE session_command_pending SET recovery_due_at="
                "clock_timestamp()+interval '1 hour'"
            )
        elif boundary == "foreign_scope":
            conn.execute("UPDATE session_command_pending SET tenant_id='other'")
    candidate = {"accepted_event_id": command.event_id, "session_id": command.session_id}
    if boundary == "foreign_session":
        candidate["session_id"] = uuid4()
    monkeypatch.setattr(recovery, "prepare_command_recovery", reject_preparation)
    before = _rows(dsn, "session_command_pending")
    database = PostgresDatabase(dsn, deployment_namespace=NAMESPACE)
    with pytest.raises(PreparationReached), database.connect() as conn:
        recovery._recover(
            conn,
            "other" if boundary == "foreign_namespace" else NAMESPACE,
            SCOPE,
            candidate,
            continuation_fence=handoff.lease.fence if boundary == "fenced" else None,
        )
    assert _rows(dsn, "session_command_pending") == before


def test_deferred_first_candidate_does_not_starve_next_due_command(dsn, monkeypatch):
    first = _prepare(dsn)
    _handoff(dsn, first)
    _due(dsn)
    monkeypatch.setattr(recovery, "prepare_command_recovery", reject_preparation)
    assert (
        recovery.recover_command_batch(
            dsn,
            deployment_namespace=NAMESPACE,
            scope=SCOPE,
            batch_size=1,
        )[0].status
        is recovery.RecoveryStatus.DEFERRED
    )
    from tests.agent_storage.test_command_wakeup import _command
    from tests.agent_storage.test_postgres_command_wakeup import _seed, _store

    second = _command(_seed(dsn).session_id, sequence=3, key="next-due")
    _store(dsn).append(second)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE session_command_pending SET recovery_due_at=clock_timestamp() "
            "WHERE accepted_event_id=%s",
            (second.event_id,),
        )
    with pytest.raises(PreparationReached):
        recovery.recover_command_batch(
            dsn, deployment_namespace=NAMESPACE, scope=SCOPE, batch_size=1
        )


def test_preflight_miss_releases_all_lifecycle_locks_before_preparation(dsn, monkeypatch):
    command = _prepare(dsn)
    _handoff(dsn, command)
    # A future due date makes the conditional UPDATE miss after taking lease locks.
    database = PostgresDatabase(dsn, deployment_namespace=NAMESPACE)

    def check_released(*args, continuation=None):
        with database.connect() as observer:
            assert observer.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired",
                (f"{NAMESPACE}:{command.session_id}",),
            ).fetchone()["acquired"]
            for table in ("worker_leases", "session_command_pending", "control_plane_epochs"):
                from psycopg import sql

                assert observer.execute(
                    sql.SQL("SELECT 1 FROM {} FOR UPDATE NOWAIT").format(sql.Identifier(table))
                ).fetchall()
        raise PreparationReached

    monkeypatch.setattr(recovery, "prepare_command_recovery", check_released)
    with pytest.raises(PreparationReached), database.connect() as conn:
        recovery._recover(
            conn,
            NAMESPACE,
            SCOPE,
            {"accepted_event_id": command.event_id, "session_id": command.session_id},
        )
