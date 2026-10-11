"""Native execution boundaries reject concurrent changes without lineage replay."""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_transactions import validate_write
from agent_storage.postgres.task_admission import load_session_task_binding, save_task_binding
from psycopg.types.json import Jsonb

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_model_cloud_fixtures import model_cloud  # noqa: F401


def prepare(env):
    database = env.database
    return PostgresCoverageAuthority.prepare(
        database, env.session, env.task_binding, env.fence,
        lambda session: load_session_task_binding(
            env.dsn, deployment_namespace=database.deployment_namespace, session_id=session,
        ),
    )


def other_session(connection, session):
    identifier = uuid4()
    connection.execute(
        "INSERT INTO session_projections(deployment_namespace,session_id,title,status,"
        "created_at,updated_at,current_sequence,namespace_id) "
        "SELECT deployment_namespace,%s,title,status,created_at,updated_at,current_sequence,"
        "namespace_id FROM session_projections WHERE session_id=%s", (identifier, session),
    )
    return identifier


def move_active(connection, session):
    target = other_session(connection, session)
    connection.execute(
        "INSERT INTO execution_segments(deployment_namespace,session_id,task_id,predecessor_id,"
        "segment_index,visibility,rollover_reason) SELECT deployment_namespace,%s,task_id,"
        "session_id,segment_index+1,visibility,'recovery' FROM execution_segments "
        "WHERE session_id=%s", (target, session),
    )
    connection.execute(
        "UPDATE agent_tasks SET active_segment_id=%s WHERE task_id=%s", (target, session),
    )


def test_boundary_uses_lease_then_fresh_authority_without_binding_loader(model_cloud, monkeypatch):
    env = model_cloud
    context = prepare(env)
    assert context is not None
    statements = []
    original = psycopg.Connection.execute

    def traced(connection, query, *args, **kwargs):
        statements.append(query)
        return original(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", traced)
    for _ in range(4):
        assert context.check() >= 0
    assert len(statements) == 8
    assert all("derive_lineage" not in query for query in statements)
    assert all("ORDER BY binding_revision DESC LIMIT 1" in query for query in statements[1::2])
    statements.clear()
    for _ in range(4):
        assert context.check_lineage() >= 0
    assert len(statements) == 4
    assert all("FROM epoch e JOIN worker_leases" not in query for query in statements)


def test_committed_binding_renewal_is_visible_without_ttl(model_cloud):
    env = model_cloud
    context = prepare(env)
    changed = env.task_binding.model_copy(update={
        "binding_revision": env.task_binding.binding_revision + 1,
    })
    save_task_binding(
        env.dsn, deployment_namespace=env.database.deployment_namespace, binding=changed,
        expected_previous_revision=env.task_binding.binding_revision,
    )
    with pytest.raises(ValueError, match="authority changed"):
        context.check()


@pytest.mark.parametrize("change", ["lineage", "namespace", "status", "active", "stop"])
def test_native_mutation_rejects_and_rollback_restores_context(model_cloud, change):
    env = model_cloud
    context = prepare(env)

    class Rollback(Exception):
        pass

    with pytest.raises(Rollback), env.database.connect() as connection:
        if change in {"namespace", "status"}:
            column, value = ("namespace_id", "other") if change == "namespace" else (
                "status", "cancelled",
            )
            connection.execute(
                f"UPDATE session_projections SET {column}=%s WHERE session_id=%s",
                (value, env.session),
            )
        elif change == "active":
            move_active(connection, env.session)
        else:
            connection.execute(
                "UPDATE session_events SET event_type=%s,payload=%s WHERE session_id=%s "
                "AND sequence=0",
                ("session_handoff_committed" if change == "lineage"
                 else "session_command_accepted", Jsonb({"kind": "stop"}), env.session),
            )
        # A second connection cannot see uncommitted changes.
        assert context.check() >= 0
        raise Rollback
    assert context.check() >= 0
    with env.database.connect() as connection:
        if change in {"namespace", "status"}:
            connection.execute(
                f"UPDATE session_projections SET {column}=%s WHERE session_id=%s",
                (value, env.session),
            )
        elif change == "active":
            move_active(connection, env.session)
        else:
            connection.execute(
                "UPDATE session_events SET event_type=%s,payload=%s WHERE session_id=%s "
                "AND sequence=0",
                ("session_handoff_committed" if change == "lineage"
                 else "session_command_accepted", Jsonb({"kind": "stop"}), env.session),
            )
    with pytest.raises(ValueError, match="authority changed"):
        context.check()


def test_version_roots_reject_direct_edits_and_other_sessions_do_not_invalidate(model_cloud):
    env = model_cloud
    context = prepare(env)
    with pytest.raises(psycopg.errors.RaiseException), env.database.connect() as connection:
        connection.execute("UPDATE coverage_lineage_versions SET revision=revision+1")
    with env.database.connect() as connection:
        other_session(connection, env.session)
    assert context.check() >= 0


def test_released_or_replaced_lease_is_not_current(model_cloud):
    env = model_cloud
    context = prepare(env)
    env.leases.release(env.session, fence=env.fence)
    with pytest.raises(LeaseLostError):
        context.check()
    # Read-only recovery validation deliberately grants no new mutation fence.
    assert context.check_lineage() >= 0
    with env.database.connect() as connection:
        connection.execute("UPDATE session_projections SET namespace_id='revoked' "
                           "WHERE session_id=%s", (env.session,))
    with pytest.raises(ValueError, match="authority changed"):
        context.check_lineage()


def test_all_native_write_authority_facts_share_two_post_lock_queries(model_cloud, monkeypatch):
    env = model_cloud
    statements = []
    original = psycopg.Connection.execute

    def traced(connection, query, *args, **kwargs):
        statements.append(query)
        return original(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", traced)
    with env.database.connect() as connection:
        _, digest, revision = validate_write(
            connection, env.database.deployment_namespace, env.binding, env.fence,
        )
    assert digest == env.task_binding.binding_digest
    assert revision == env.task_binding.binding_revision
    assert len(statements) == 2


def test_normal_recovery_reuses_only_exact_current_wake_context(model_cloud):
    from zebra_agent_worker.coverage_recovery_authority import prepare_recovery_authority

    env = model_cloud
    context = prepare(env)
    runtime = SimpleNamespace(dsn=env.dsn, metadata=SimpleNamespace(_database=env.database))
    service = SimpleNamespace(_task_binding_loader=Mock(side_effect=AssertionError("full replay")))
    policy = SimpleNamespace(
        deadline=env.task_binding.host_capability.host_context.expires_at,
        started_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    current = prepare_recovery_authority(
        runtime, service, env.session, env.task_binding, env.fence, policy,
        issued=False, execution_authority=context,
    )
    current()
    for field, value in (
        ("session", uuid4()),
        ("fence", env.fence.model_copy(update={"owner_instance_id": uuid4()})),
        ("binding", env.task_binding.model_copy(update={"binding_revision": 99})),
    ):
        original = getattr(context, field)
        setattr(context, field, value)
        try:
            with pytest.raises(ValueError, match="another wake or scope"):
                prepare_recovery_authority(
                    runtime, service, env.session, env.task_binding, env.fence, policy,
                    issued=False, execution_authority=context,
                )
        finally:
            setattr(context, field, original)
    with env.database.connect() as connection:
        connection.execute("UPDATE session_projections SET namespace_id='revoked' "
                           "WHERE session_id=%s", (env.session,))
    with pytest.raises(ValueError, match="authority changed"):
        current()
    service._task_binding_loader.assert_not_called()


def test_permission_committed_during_lease_wait_uses_post_lock_snapshot(model_cloud, monkeypatch):
    env = model_cloud
    context = prepare(env)
    started = Event()
    original = psycopg.Connection.execute

    def traced(connection, query, *args, **kwargs):
        if type(query) is str and "FROM epoch e JOIN worker_leases" in query:
            started.set()
        return original(connection, query, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with env.database.connect() as writer:
            writer.execute("SELECT 1 FROM worker_leases WHERE session_id=%s FOR UPDATE",
                           (env.session,))
            monkeypatch.setattr(psycopg.Connection, "execute", traced)
            future = pool.submit(context.check)
            assert started.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            writer.execute("UPDATE session_projections SET namespace_id='revoked' "
                           "WHERE session_id=%s", (env.session,))
        with pytest.raises(ValueError, match="authority changed"):
            future.result(timeout=5)
