"""Real PG scheduling across two engine identities; engine removal itself is a fake."""

import json
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_runtime.force_stop_cleanup import recover_force_stops
from agent_storage.postgres.command_runtime_cleanup import settle_runtime_cleanup
from agent_storage.postgres.command_wakeup_control import handle_control_command
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.force_stop_executors import acknowledge_executor, register_executor
from agent_storage.postgres.force_stop_recovery import PostgresForceStopRecovery
from zebra_agent_api import RouteAdapter

from tests.agent_storage.test_postgres_command_runtime_cleanup import _claim, _prepare_cleanup
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup import dsn as shared_dsn
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as shared_postgres
from tests.agent_storage.test_postgres_command_wakeup_control import _intent
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_direct_control import _cancel
from tests.agent_storage.test_postgres_direct_control_api import _app
from tests.agent_storage.test_postgres_force_stop_recovery import due
from tests.agent_storage.test_postgres_force_stops import _force, _progress
from tests.agent_storage.test_postgres_runtime_instances import _instances, _setup

dsn, postgres_dsn = shared_dsn, shared_postgres
FIRST, SECOND = "a" * 64, "c" * 64


def obligations(dsn):
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            "SELECT cleanup_id,status,attempts,available_at,claim_fence,error_code "
            "FROM command_runtime_cleanup ORDER BY available_at,cleanup_id"
        ).fetchall()


def test_foreign_cleaner_cannot_spend_owner_retry_or_delay_budget(dsn):
    _prepare_cleanup(dsn)
    before = obligations(dsn)
    for _ in range(40):
        assert _claim(dsn, engine_identity=SECOND) is None
    assert obligations(dsn) == before
    claim = _claim(dsn, engine_identity=FIRST)
    assert claim and claim.leased
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)


def test_foreign_oldest_obligation_cannot_hide_local_work(dsn):
    first, _ = _prepare_cleanup(dsn)
    second, _ = _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE runtime_instances SET engine_identity=%s WHERE instance_id=%s",
            (SECOND, second),
        )
    before = obligations(dsn)[0]
    claim = _claim(dsn, engine_identity=SECOND)
    assert claim and claim.target and str(claim.target.instance_id) == second
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)
    assert obligations(dsn)[0] == before
    claim = _claim(dsn, engine_identity=FIRST)
    assert claim and claim.target and str(claim.target.instance_id) == first
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)


def forced(dsn, engines):
    lease = _setup(dsn)
    # Unit-level exit fact; real Linux witness/ACK is covered by executor-capacity tests.
    database = PostgresDatabase(dsn, deployment_namespace=NAMESPACE)
    register_executor(database, lease.session_id, lease.fence)
    acknowledge_executor(database, lease.session_id, lease.fence)
    for number, engine in enumerate(engines, 1):
        instances = _instances(dsn, lease, engine=engine)
        instance = str(uuid4())
        instances.reserve(instance, str(lease.session_id), "d" * 64)
        instances.created(instance, str(number) * 64)
    adapter = RouteAdapter(_app(dsn))
    assert adapter.handle(_force(lease.session_id)).status_code == 202
    return adapter, lease.session_id


def diagnostics(dsn):
    with psycopg.connect(dsn) as connection:
        return json.loads(connection.execute(
            "SELECT diagnostics FROM agent_safety_overrides WHERE reason='user_force_stop'"
        ).fetchone()[0])


def recover(dsn, engine):
    return recover_force_stops(
        dsn, deployment_namespace=NAMESPACE,
        engine=None if engine is None else SimpleNamespace(identity=engine)
    )


def remove_matching(engine, command, target, timeout):
    assert dict(target.labels)["zebra.agent.engine"] == engine.identity
    return target.container_id, None


@pytest.mark.parametrize("wrong", [SECOND, None])
def test_wrong_stop_cleaner_cannot_exhaust_owner_attempts(dsn, monkeypatch, wrong):
    adapter, sid = forced(dsn, [FIRST])
    monkeypatch.setattr("agent_runtime.force_stop_cleanup._remove_exact", remove_matching)
    assert recover(dsn, wrong) == 0  # First pass may record/revoke the frontier.
    before = diagnostics(dsn)
    for _ in range(20):
        due(dsn)
        assert recover(dsn, wrong) == 0
    after = diagnostics(dsn)
    assert after["attempts"] == before["attempts"]
    assert after["phase"] == "stopping"
    due(dsn)
    assert recover(dsn, FIRST) == 1, diagnostics(dsn).get("error_code")
    assert adapter.handle(_progress(sid)).body["resources_released"]


def test_mixed_engine_stop_advances_on_each_exact_owner(dsn, monkeypatch):
    adapter, sid = forced(dsn, [FIRST, SECOND])
    monkeypatch.setattr("agent_runtime.force_stop_cleanup._remove_exact", remove_matching)
    assert recover(dsn, FIRST) == 0
    assert not adapter.handle(_progress(sid)).body["resources_released"]
    before = diagnostics(dsn)["attempts"]
    for _ in range(20):
        due(dsn)
        assert recover(dsn, FIRST) == 0
    assert diagnostics(dsn)["attempts"] == before
    due(dsn)
    assert recover(dsn, SECOND) == 1, diagnostics(dsn).get("error_code")
    assert adapter.handle(_progress(sid)).body["resources_released"]


def test_other_fence_on_local_engine_cannot_hide_later_local_work(dsn):
    lease = _setup(dsn)
    stale = None
    for engine in (FIRST, SECOND):
        store = _instances(dsn, lease, engine=engine)
        instance = str(uuid4())
        store.reserve(instance, str(lease.session_id), "d" * 64)
        store.created(instance, "b" * 64)
        if engine == SECOND:
            stale = instance
    with psycopg.connect(dsn) as c:
        c.execute("UPDATE runtime_instances SET fencing_token=fencing_token+99 "
                  "WHERE instance_id=%s", (stale,))
    command = _intent(dsn, lease.session_id, "cancel")
    handle_control_command(dsn, deployment_namespace=NAMESPACE, scope=SCOPE,
                           accepted_event_id=command.event_id)
    local, _ = _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as c:
        c.execute("UPDATE runtime_instances SET engine_identity=%s WHERE instance_id=%s",
                  (SECOND, local))
    claim = _claim(dsn, engine_identity=SECOND)
    assert claim and claim.target and str(claim.target.instance_id) == local
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)


def test_expired_foreign_obligation_remains_quarantinable(dsn):
    _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as c:
        c.execute(
            "UPDATE command_runtime_cleanup SET created_at=clock_timestamp()-interval '2 days'"
        )
    claim = _claim(dsn, engine_identity=SECOND)
    assert claim and not claim.leased
    assert obligations(dsn)[0][1] == "requires_reconciliation"


def test_direct_control_anchor_routes_to_exact_owner_without_foreign_attempts(dsn):
    lease = _setup(dsn)
    runtime, instance = _instances(dsn, lease), str(uuid4())
    runtime.reserve(instance, str(lease.session_id), "d" * 64)
    runtime.created(instance, "b" * 64)
    _cancel(dsn, lease.session_id, operation_id=uuid4())
    before = obligations(dsn)
    for _ in range(3):
        assert _claim(dsn, engine_identity=SECOND) is None
    assert obligations(dsn) == before
    claim = _claim(dsn, engine_identity=FIRST)
    assert claim and claim.direct_operation_id and claim.target
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)


def test_foreign_cleaner_retries_shared_control_after_revocation_failure(dsn, monkeypatch):
    _, sid = forced(dsn, [FIRST])
    original, calls = PostgresForceStopRecovery.revoke, []

    def fail_once(store, target):
        calls.append(target)
        if len(calls) == 1:
            raise RuntimeError("synthetic transient revocation failure")
        return original(store, target)

    monkeypatch.setattr(PostgresForceStopRecovery, "revoke", fail_once)
    assert recover(dsn, SECOND) == 0
    assert diagnostics(dsn)["lease"] == "unconfirmed"
    due(dsn)
    assert recover(dsn, SECOND) == 0
    after = diagnostics(dsn)
    assert after["lease"] == "revoked" and after["synchronization"] == "synchronized"
    assert not RouteAdapter(_app(dsn)).handle(_progress(sid)).body["resources_released"]
    due(dsn)
    assert recover(dsn, SECOND) == 0
    assert diagnostics(dsn)["attempts"] == after["attempts"]


def test_absolute_stop_deadline_remains_visible_without_own_engine(dsn):
    _, sid = forced(dsn, [FIRST])
    assert recover(dsn, SECOND) == 0
    with psycopg.connect(dsn) as c:
        # Scheduling-only fixture: do not execute the deliberately altered admission metadata.
        c.execute("""UPDATE agent_safety_overrides SET diagnostics=jsonb_set(
            diagnostics::jsonb,'{accepted_at}',to_jsonb(
                (clock_timestamp()-interval '11 minutes')::text))::text
            WHERE reason='user_force_stop'""")
    due(dsn)
    store = PostgresForceStopRecovery(dsn, deployment_namespace=NAMESPACE)
    assert sid in store.pending(engine_identity=SECOND)
    assert sid in store.pending(engine_identity=None)
