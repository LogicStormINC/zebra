"""Fresh-schema stop/capacity regression; executor ACKs are injected unit facts."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from agent_runtime.process_supervision import supervise_process
from agent_storage.postgres import force_stop_recovery
from agent_storage.postgres.command_wakeup import CommandAdmissionCapacityError
from agent_storage.postgres.command_wakeup_pickup import discover_command_pickups
from agent_storage.postgres.force_stop_executors import (
    executor_key,
    executor_monitor,
    executors_exited,
    register_executor,
)
from agent_storage.postgres.force_stop_recovery import PostgresForceStopRecovery
from agent_storage.postgres.force_stops import PostgresForceStops
from agent_storage.postgres.leases import lock_session_lease_boundary
from psycopg import sql
from psycopg.rows import dict_row
from zebra_agent_api import RouteAdapter

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_direct_control import _rows
from tests.agent_storage.test_postgres_direct_control_api import _app
from tests.agent_storage.test_postgres_force_stop_recovery import due, recover
from tests.agent_storage.test_postgres_force_stops import _force, _progress
from tests.agent_storage.test_postgres_lease_clock import _wait_locked, _worker_dsn

postgres_dsn, dsn = _pg_fixture, _dsn_fixture


def capacity(dsn, label):
    with psycopg.connect(dsn) as connection:
        count = connection.execute(
            "SELECT count(*) FROM session_command_pending WHERE status='pending' "
            "AND command_kind IN ('run','resume','message')"
        ).fetchone()[0]
    print("Q1_CAPACITY " + json.dumps({"label": label, "pending": count}))
    return count


@pytest.fixture(autouse=True)
def audit(dsn, request):
    yield
    rows = _rows(dsn, "session_command_pending")
    receipts = _rows(dsn, "command_handoff_receipts")
    print(
        "Q1_STATE "
        + json.dumps(
            {
                "case": request.node.name,
                "commands": [
                    {
                        k: row[k]
                        for k in [
                            "session_id",
                            "accepted_event_id",
                            "status",
                            "cancelled_by_control_id",
                        ]
                    }
                    for row in rows
                ],
                "handled": [r["handled_event_id"] for r in receipts],
                "models": sum(
                    e["event_type"] == "model_request_started" for e in _rows(dsn, "session_events")
                ),
            },
            default=str,
        )
    )
    if directory := os.environ.get("Q1_ARTIFACT_DIRECTORY"):
        tables = [
            "session_command_pending",
            "command_handoff_receipts",
            "agent_safety_overrides",
            "worker_leases",
            "control_plane_idempotency_records",
            "session_events",
        ]
        path = Path(directory) / (request.node.name + ".json")
        with path.open("x") as file:
            json.dump({name: _rows(dsn, name) for name in tables}, file, default=str)


def test_queued_stop_releases_capacity_without_lease_executor_or_handled_event(dsn):
    event = _prepare(dsn)
    adapter = RouteAdapter(_app(dsn))
    assert capacity(dsn, "queued-before") == 1
    assert adapter.handle(_force(event.session_id)).status_code == 202
    assert capacity(dsn, "queued-requested") == 1
    assert recover(dsn) == 1
    assert capacity(dsn, "queued-settled") == 0
    assert _rows(dsn, "session_command_pending")[0]["status"] == "cancelled"
    assert not _rows(dsn, "worker_leases")
    assert not _rows(dsn, "command_handoff_receipts")
    assert not discover_command_pickups(dsn, deployment_namespace=NAMESPACE, lane="execution")
    assert adapter.handle(_progress(event.session_id)).body["resources_released"]


def test_running_stop_retains_capacity_until_exact_ack_and_repeats_are_idempotent(dsn):
    event = _prepare(dsn)
    lease = _handoff(dsn, event).lease
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    register_executor(stops.database, event.session_id, lease.fence)
    adapter = RouteAdapter(_app(dsn))
    original = adapter.handle(_force(event.session_id))
    assert original.status_code == 202
    assert recover(dsn) == 0
    assert capacity(dsn, "running-no-exit") == 1
    assert _rows(dsn, "worker_leases")[0]["released_at"] is not None
    assert not adapter.handle(_progress(event.session_id)).body["resources_released"]
    stops.acknowledge_executor(
        event.session_id, lease.fence.model_copy(update={"fencing_token": 99})
    )
    due(dsn)
    assert recover(dsn) == 0
    assert capacity(dsn, "running-wrong-ack") == 1
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(stops.acknowledge_executor, event.session_id, lease.fence) for _ in range(2)
        ]
        for future in futures:
            future.result(timeout=5)
    due(dsn)
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(recover, [dsn, dsn])) == 1
    assert capacity(dsn, "running-exact-ack") == 0
    assert adapter.handle(_force(event.session_id)) == original
    assert adapter.handle(_force(event.session_id, key="second-stop")).status_code == 200
    assert recover(dsn) == 0
    assert capacity(dsn, "running-repeated") == 0
    assert _rows(dsn, "command_handoff_receipts")[0]["handled_event_id"] is None
    exits = [
        r for r in _rows(dsn, "control_plane_idempotency_records") if r["action"] == "executor_exit"
    ]
    assert len(exits) == 1
    assert (
        len([e for e in _rows(dsn, "session_events") if e["event_type"] == "session_cancelled"])
        == 1
    )


@pytest.mark.parametrize("collation", ["C", "en-US-x-icu", "icu-nondeterministic"])
def test_exact_exit_receipt_is_independent_of_collation(dsn, collation):
    event = _prepare(dsn)
    sid = event.session_id
    fence = _handoff(dsn, event).lease.fence
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    key = executor_key(sid, fence)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        source = "en-US-x-icu" if collation == "icu-nondeterministic" else collation
        available = connection.execute(
            "SELECT 1 FROM pg_collation WHERE collname=%s", (source,)
        ).fetchone()
        if available is None:
            pytest.skip(f"PostgreSQL collation {collation} is unavailable")
        identifier = sql.Identifier("pg_catalog", collation)
        if collation == "icu-nondeterministic":
            connection.execute(
                "CREATE COLLATION q1_icu (provider=icu, locale='und-u-ks-level1', "
                "deterministic=false)"
            )
            identifier = sql.Identifier("q1_icu")
        connection.execute(
            sql.SQL(
                "ALTER TABLE control_plane_idempotency_records "
                "ALTER COLUMN idempotency_key TYPE text COLLATE {}"
            ).format(identifier)
        )
    register_executor(stops.database, sid, fence)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        lease = connection.execute("SELECT * FROM worker_leases").fetchone()
        assert lease is not None

        def insert_receipt(action, receipt_key, wrong_body=False):
            connection.execute(
                """INSERT INTO control_plane_idempotency_records
                SELECT deployment_namespace, %s, %s, request_hash, status_code,
                       CASE WHEN %s THEN '{}'::jsonb ELSE response_body END, created_at
                FROM control_plane_idempotency_records
                WHERE deployment_namespace=%s AND action='executor_started'
                  AND idempotency_key=%s""",
                (action, receipt_key, wrong_body, NAMESPACE, key),
            )

        insert_receipt("executor_started", f"{sid}0:nearby")
        insert_receipt(
            "executor_exit",
            executor_key(sid, fence.model_copy(update={"fencing_token": fence.fencing_token + 1})),
        )
        assert not executors_exited(connection, NAMESPACE, sid, lease)
        insert_receipt("executor_exit", key, wrong_body=True)
        assert not executors_exited(connection, NAMESPACE, sid, lease)
        connection.execute(
            "DELETE FROM control_plane_idempotency_records WHERE action='executor_exit'"
        )
    stops.acknowledge_executor(sid, fence)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        assert executors_exited(connection, NAMESPACE, sid, lease)


def test_lease_without_registered_executor_is_not_exit_evidence(dsn):
    event = _prepare(dsn)
    _handoff(dsn, event)
    assert RouteAdapter(_app(dsn)).handle(_force(event.session_id)).status_code == 202
    assert recover(dsn) == 0
    assert capacity(dsn, "unregistered-lease-no-proof") == 1
    assert _rows(dsn, "worker_leases")[0]["released_at"] is not None


def test_single_slot_accepts_replacement_only_after_exact_exit(dsn):
    event = _prepare(dsn)
    lease = _handoff(dsn, event).lease
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    register_executor(stops.database, event.session_id, lease.fence)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_wakeup_rollouts SET max_pending_per_scope=1")
    replacement = _command(_seed(dsn).session_id, key="replacement")
    adapter = RouteAdapter(_app(dsn))
    assert adapter.handle(_force(event.session_id)).status_code == 202
    assert recover(dsn) == 0
    with pytest.raises(CommandAdmissionCapacityError, match="command_scope_capacity"):
        _store(dsn).append(replacement)
    assert capacity(dsn, "single-slot-before-exit") == 1
    stops.acknowledge_executor(event.session_id, lease.fence)
    due(dsn)
    assert recover(dsn) == 1
    assert capacity(dsn, "single-slot-released") == 0
    assert _store(dsn).append(replacement) == replacement
    assert _store(dsn).append(replacement) == replacement
    assert capacity(dsn, "single-slot-reused-once") == 1
    with pytest.raises(CommandAdmissionCapacityError, match="command_scope_capacity"):
        _store(dsn).append(_command(_seed(dsn).session_id, key="third"))
    assert capacity(dsn, "single-slot-no-double-release") == 1


def test_stop_wins_while_pickup_waits_on_the_session_boundary(dsn):
    event = _prepare(dsn)
    with (
        ThreadPoolExecutor(1) as pool,
        psycopg.connect(dsn) as blocker,
        psycopg.connect(dsn, autocommit=True) as observer,
    ):
        lock_session_lease_boundary(blocker, NAMESPACE, event.session_id)
        future = pool.submit(_handoff, _worker_dsn(dsn, "q1-claim"), event)
        try:
            _wait_locked(observer, "q1-claim")
            assert RouteAdapter(_app(dsn)).handle(_force(event.session_id)).status_code == 202
            assert capacity(dsn, "claim-blocked-stop-requested") == 1
        finally:
            blocker.rollback()
        assert future.result(timeout=5).lease is None
    assert recover(dsn) == 1
    assert capacity(dsn, "claim-race-settled") == 0
    assert not _rows(dsn, "worker_leases")
    assert not [
        r
        for r in _rows(dsn, "control_plane_idempotency_records")
        if r["action"] == "executor_started"
    ]


def test_cleaner_process_exit_after_sync_is_resumed_without_replay(dsn):
    event = _prepare(dsn)
    assert RouteAdapter(_app(dsn)).handle(_force(event.session_id)).status_code == 202
    code = """
import os
from agent_runtime.force_stop_cleanup import recover_force_stops
from agent_storage.postgres.force_stop_recovery import PostgresForceStopRecovery
original = PostgresForceStopRecovery.synchronize
def interrupted(self, data, target):
    original(self, data, target)
    os._exit(71)
PostgresForceStopRecovery.synchronize = interrupted
recover_force_stops(os.environ['Q1_DSN'], deployment_namespace='command-wakeup-test', engine=None)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "Q1_DSN": dsn},
        capture_output=True,
        text=True,
        timeout=12,
    )
    assert result.returncode == 71, result.stderr
    assert capacity(dsn, "cleaner-exited-after-sync") == 0
    store = PostgresForceStopRecovery(dsn, deployment_namespace=NAMESPACE)
    assert store.pending() == [event.session_id]
    events = _rows(dsn, "session_events")
    assert recover(dsn) == 1
    assert capacity(dsn, "cleaner-recovered") == 0
    assert _rows(dsn, "session_events") == events
    assert not store.pending()


def test_real_child_exit_still_requires_durable_ack_before_capacity_release(dsn):
    event = _prepare(dsn)
    lease = _handoff(dsn, event).lease
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    register_executor(stops.database, event.session_id, lease.fence)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time;print('ready',flush=True);time.sleep(30)"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    exited = []
    try:
        assert child.stdout.readline().strip() == "ready"
        assert RouteAdapter(_app(dsn)).handle(_force(event.session_id)).status_code == 202
        assert recover(dsn) == 0 and child.poll() is None
        assert capacity(dsn, "real-child-alive") == 1
        with executor_monitor(stops.database, event.session_id) as cancelled:
            assert supervise_process(
                child, cancelled, interval=0.01, on_exit=lambda: exited.append(child.returncode)
            )
        assert len(exited) == 1 and exited[0] < 0
        print("Q1_CHILD_EXIT " + json.dumps({"pid": child.pid, "returncode": child.returncode}))
        due(dsn)
        assert recover(dsn) == 0
        assert capacity(dsn, "real-child-exited-ack-missing") == 1
        stops.acknowledge_executor(event.session_id, lease.fence)
        due(dsn)
        assert recover(dsn) == 1
        assert capacity(dsn, "real-child-exit-acked") == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdout.close()


def test_failed_canonical_sync_rolls_back_capacity_and_existing_recovery_finishes(dsn, monkeypatch):
    event = _prepare(dsn)
    assert RouteAdapter(_app(dsn)).handle(_force(event.session_id)).status_code == 202
    original = force_stop_recovery.cancel_in_transaction

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic pre-commit interruption")

    with monkeypatch.context() as patch:
        patch.setattr(force_stop_recovery, "cancel_in_transaction", interrupted)
        assert recover(dsn) == 0
    assert capacity(dsn, "sync-rolled-back") == 1
    assert not [e for e in _rows(dsn, "session_events") if e["event_type"] == "session_cancelled"]
    due(dsn)
    assert recover(dsn) == 1
    assert capacity(dsn, "sync-recovered") == 0
