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
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_transactions import validate_write
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.task_admission import load_session_task_binding, save_task_binding

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


def append_authority_change(connection, env, change):
    namespace = env.database.deployment_namespace
    version = connection.execute(
        "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
        "AND session_id=%s", (namespace, env.session),
    ).fetchone()["current_version"]
    if change == "stop":
        command = SessionCommand(
            session_id=env.session, kind=SessionCommandKind.STOP,
            expected_revision=version, idempotency_key=str(uuid4()),
        )
        kind, key = EventType.SESSION_COMMAND_ACCEPTED, command.idempotency_key
        payload = {**command.model_dump(mode="json"), "fingerprint": command.fingerprint}
    else:
        kind, key = EventType.SESSION_HANDOFF_COMMITTED, None
        payload = {
            "handoff_id": str(uuid4()), "target_session_id": str(uuid4()),
            "reason": "internal_recovery", "target_stage_index": 1,
            "source_event_range": {"start_sequence": 0, "end_sequence": version},
            "source_event_hash": "a" * 64, "artifact_id": str(uuid4()),
            "checksum": "b" * 64, "idempotency_key_hash": "c" * 64,
        }
    append_event_in_transaction(connection, namespace, SessionEvent.create(
        session_id=env.session, sequence=version + 1, event_type=kind,
        actor=EventActor.SYSTEM, payload=payload, idempotency_key=key,
    ))


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


@pytest.mark.parametrize("boundary", ["check", "observe"])
def test_committed_binding_renewal_is_visible_without_ttl(model_cloud, boundary):
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
        getattr(context, boundary)()


@pytest.mark.parametrize("change", ["lineage", "namespace", "status", "active", "stop"])
@pytest.mark.parametrize("boundary", ["check", "observe"])
def test_native_mutation_rejects_and_rollback_restores_context(model_cloud, change, boundary):
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
            append_authority_change(connection, env, change)
        # A second connection cannot see uncommitted changes.
        assert getattr(context, boundary)() >= 0
        raise Rollback
    assert getattr(context, boundary)() >= 0
    with env.database.connect() as connection:
        if change in {"namespace", "status"}:
            connection.execute(
                f"UPDATE session_projections SET {column}=%s WHERE session_id=%s",
                (value, env.session),
            )
        elif change == "active":
            move_active(connection, env.session)
        else:
            append_authority_change(connection, env, change)
    with pytest.raises(ValueError, match="authority changed"):
        getattr(context, boundary)()


def test_version_roots_reject_direct_edits_and_other_sessions_do_not_invalidate(model_cloud):
    env = model_cloud
    context = prepare(env)
    with pytest.raises(psycopg.errors.RaiseException), env.database.connect() as connection:
        connection.execute("UPDATE coverage_lineage_versions SET revision=revision+1")
    with env.database.connect() as connection:
        other_session(connection, env.session)
    assert context.check() >= 0


@pytest.mark.parametrize("boundary", ["check", "observe"])
def test_released_or_replaced_lease_is_not_current(model_cloud, boundary):
    env = model_cloud
    context = prepare(env)
    env.leases.release(env.session, fence=env.fence)
    with pytest.raises(LeaseLostError):
        getattr(context, boundary)()
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


def test_readonly_observation_one_snapshot_and_borrowed_owner_keeps_post_lock(
    model_cloud, monkeypatch,
):
    from agent_storage.postgres.work_unit import postgres_work_unit

    env = model_cloud
    context = prepare(env)
    statements = []
    original = psycopg.Connection.execute

    def traced(connection, query, *args, **kwargs):
        statements.append(query)
        return original(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", traced)
    assert context.observe() >= 0
    assert len(statements) == 1 and "LEFT JOIN worker_leases" in statements[0]
    assert "FOR SHARE" not in statements[0]
    statements.clear()
    with postgres_work_unit(env.database):
        assert context.observe() >= 0
    assert len(statements) == 2 and "FOR SHARE" in statements[0]
    assert "snapshot_json" in statements[1]


@pytest.mark.parametrize("change", ["missing", "owner", "fence", "epoch", "expiry", "deadline"])
def test_observation_never_caches_current_lease_or_deadline(model_cloud, change):
    env = model_cloud
    context = prepare(env)
    assert context.observe() >= 0
    with env.database.connect() as connection:
        if change == "missing":
            connection.execute("DELETE FROM worker_leases WHERE session_id=%s", (env.session,))
        elif change == "epoch":
            connection.execute("UPDATE control_plane_epochs SET epoch=%s", (uuid4(),))
        elif change != "deadline":
            column, value = {
                "owner": ("owner_instance_id", uuid4()),
                "fence": ("fencing_token", env.fence.fencing_token + 1),
                "expiry": ("expires_at", datetime.now(UTC) - timedelta(seconds=1)),
            }[change]
            connection.execute(f"UPDATE worker_leases SET {column}=%s WHERE session_id=%s",
                               (value, env.session))
    with pytest.raises(ValueError if change == "deadline" else LeaseLostError):
        context.observe(deadline=datetime.now(UTC) if change == "deadline" else None)
