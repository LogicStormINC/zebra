"""Native Task proof is bounded; current authority and full certification stay fresh."""
# ruff: noqa: F811

from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import coverage_model_source as source
from agent_storage.postgres.coverage_task_summary import admitted_task_origin
from agent_storage.postgres.coverage_task_summary_migration import (
    COVERAGE_TASK_SUMMARY_MIGRATION as MIGRATION,
)
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.task_admission import save_task_binding
from psycopg.types.json import Jsonb

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_model_cloud_fixtures import model_cloud  # noqa: F401
from tests.worker.test_coverage_model_acceptance import settled

pytestmark = pytest.mark.parametrize(
    "model_cloud", [{"validation_mode": "final_certification"}], indirect=True,
)


class RollbackProbe(Exception):
    pass


def test_normal_task_proof_is_bounded_but_final_policy_replays(model_cloud, monkeypatch):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        expected = source.task_policy(connection, env.store._deployment, env.binding)
        assert admitted_task_origin(connection, env.store._deployment, env.binding) is not None
        statements = []

        class Read:
            def execute(self, sql, args):
                statements.append(sql)
                assert "session_events" not in sql, "history scan on normal Task proof"
                return connection.execute(sql, args)

        assert source.task_policy(
            Read(), env.store._deployment, env.binding, incremental=True,
        ) == expected
        assert len(statements) == 2  # Native continuity proof and latest uncached authority.
        with monkeypatch.context() as fast:
            fast.setattr(source, "task_events", lambda *args: (_ for _ in ()).throw(
                AssertionError("independent history proof"),
            ))
            assert source.task_policy(
                connection, env.store._deployment, env.binding, incremental=True,
            ) == expected
            with pytest.raises(AssertionError, match="independent history"):
                source.task_policy(connection, env.store._deployment, env.binding)


def test_history_mutation_invalidates_and_rollback_restores(model_cloud):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        origin = admitted_task_origin(connection, env.store._deployment, env.binding)
        assert origin is not None
        for statement in (
            "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
            "WHERE event_type='task_prepared'",
            "DELETE FROM session_events WHERE event_type='coverage_model_call_reserved'",
        ):
            with pytest.raises(RollbackProbe), connection.transaction():
                connection.execute(statement)
                assert admitted_task_origin(connection, env.store._deployment, env.binding) is None
                raise RollbackProbe
            assert admitted_task_origin(connection, env.store._deployment, env.binding) == origin
        # Existing append-only receipt FK descendants already refuse a cascading
        # history truncate; do not disable that independent production guard.
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            with connection.transaction():
                connection.execute("TRUNCATE session_events CASCADE")
        assert admitted_task_origin(connection, env.store._deployment, env.binding) == origin
        for statement in (
            "UPDATE coverage_task_summary SET last_sequence=0",
            "DELETE FROM coverage_task_summary",
            "TRUNCATE coverage_task_summary",
            "INSERT INTO coverage_task_summary(deployment_namespace,session_id) "
            "VALUES('foreign','00000000-0000-0000-0000-000000000000')",
        ):
            with pytest.raises(psycopg.errors.RaiseException), connection.transaction():
                connection.execute(statement)


def test_stream_and_current_binding_conflicts_are_not_cached(model_cloud):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        expected = source.task_policy(connection, env.store._deployment, env.binding)
        with pytest.raises(RollbackProbe), connection.transaction():
            connection.execute("UPDATE session_streams SET current_version=current_version+1")
            with pytest.raises(ValueError, match="unpruned exact Session history"):
                source.task_policy(connection, env.store._deployment, env.binding, incremental=True)
            raise RollbackProbe
        with pytest.raises(RollbackProbe), connection.transaction():
            connection.execute("DELETE FROM task_binding_snapshots")
            with pytest.raises(ValueError, match="no persisted Task binding"):
                source.task_policy(connection, env.store._deployment, env.binding, incremental=True)
            raise RollbackProbe
        assert source.task_policy(
            connection, env.store._deployment, env.binding, incremental=True,
        ) == expected


def test_missing_migration_and_existing_history_fall_back(model_cloud):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        expected = source.task_policy(connection, env.store._deployment, env.binding)
        with pytest.raises(RollbackProbe), connection.transaction():
            connection.execute("DELETE FROM zebra_schema_migrations WHERE version=89")
            assert admitted_task_origin(connection, env.store._deployment, env.binding) is None
            assert source.task_policy(
                connection, env.store._deployment, env.binding, incremental=True,
            ) == expected
            raise RollbackProbe


def test_task_history_growth_keeps_normal_reads_bounded_and_scoped(model_cloud):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        origin = admitted_task_origin(connection, env.store._deployment, env.binding)
        assert origin is not None
        expected = source.task_policy(connection, env.store._deployment, env.binding)
        version = connection.execute(
            "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
            "AND session_id=%s", (env.store._deployment, env.session),
        ).fetchone()["current_version"]
        # Actual native append path, not a manually populated proof projection.
        for offset in range(1, 1001):
            append_event_in_transaction(connection, env.store._deployment, origin.model_copy(
                update={"event_id": uuid4(), "sequence": version + offset, "idempotency_key": None},
            ))
        queries = []

        class Read:
            def execute(self, sql, args):
                queries.append(sql)
                assert "session_events" not in sql
                return connection.execute(sql, args)

        assert source.task_policy(
            Read(), env.store._deployment, env.binding, incremental=True,
        ) == expected
        assert len(queries) == 2
        assert admitted_task_origin(connection, "other-tenant", env.binding) is None
        assert source.task_policy(connection, env.store._deployment, env.binding) == expected
        # Test-owned schema only: recreate the migration with already existing history.
        with pytest.raises(RollbackProbe), connection.transaction():
            connection.execute("DROP TABLE coverage_task_summary CASCADE")
            connection.execute("DROP FUNCTION advance_coverage_task_summary() CASCADE")
            connection.execute("DROP FUNCTION guard_coverage_task_summary() CASCADE")
            for sql in MIGRATION.statements:
                connection.execute(sql)
            assert admitted_task_origin(connection, env.store._deployment, env.binding) is None
            assert source.task_policy(
                connection, env.store._deployment, env.binding, incremental=True,
            ) == expected
            raise RollbackProbe


def test_task_descriptor_changes_never_requalify_after_repair(model_cloud):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        expected = source.task_policy(connection, env.store._deployment, env.binding)
        original = admitted_task_origin(connection, env.store._deployment, env.binding)
        assert original is not None
        connection.execute(
            "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
            "WHERE event_type='task_prepared'",
        )
        connection.execute(
            "UPDATE session_events SET created_at=created_at-interval '1 microsecond' "
            "WHERE event_type='task_prepared'",
        )
        assert admitted_task_origin(connection, env.store._deployment, env.binding) is None
        assert source.task_policy(
            connection, env.store._deployment, env.binding, incremental=True,
        ) == expected


@pytest.mark.parametrize("gap", [False, True])
def test_new_conflicting_descriptor_or_sequence_gap_refuses(model_cloud, gap):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        origin = admitted_task_origin(connection, env.store._deployment, env.binding)
        assert origin is not None
        version = connection.execute(
            "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
            "AND session_id=%s", (env.store._deployment, env.session),
        ).fetchone()["current_version"]
        payload = dict(origin.payload)
        payload["coverage_admission"] = dict(payload["coverage_admission"])
        payload["coverage_admission"]["max_model_calls"] += 1
        if gap:
            connection.execute(
                "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
                "event_type,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (env.store._deployment, uuid4(), env.session, version+2,
                 origin.event_type.value, Jsonb(origin.payload),
                 origin.actor.value, origin.created_at),
            )
            connection.execute(
                "UPDATE session_streams SET current_version=%s WHERE deployment_namespace=%s "
                "AND session_id=%s", (version+2, env.store._deployment, env.session),
            )
        else:
            append_event_in_transaction(connection, env.store._deployment, origin.model_copy(
                update={"event_id": uuid4(), "sequence": version+1,
                        "payload": payload, "idempotency_key": None},
            ))
        assert admitted_task_origin(connection, env.store._deployment, env.binding) is None
        with pytest.raises(ValueError, match="unpruned|strict Task identity"):
            source.task_policy(connection, env.store._deployment, env.binding, incremental=True)


def test_committed_binding_renewal_is_visible_on_next_normal_read(model_cloud):
    from agent_storage.postgres.coverage_model_index import indexed_state

    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        previous = source.task_policy(
            connection, env.store._deployment, env.binding, incremental=True,
        )
        assert previous is not None
        renewed = env.task_binding.model_copy(update={
            "binding_revision": 2,
            "host_capability": env.task_binding.host_capability.model_copy(
                update={"grant_digest": "9" * 64},
            ),
        })
        save_task_binding(
            env.dsn, deployment_namespace=env.store._deployment,
            binding=renewed, expected_previous_revision=1,
        )
        current = source.task_policy(
            connection, env.store._deployment, env.binding, incremental=True,
        )
        assert current is not None and current.task_binding_digest == renewed.binding_digest
        assert current.task_binding_digest != previous.task_binding_digest
        assert source.task_policy(connection, env.store._deployment, env.binding) == current
        with pytest.raises(ValueError, match="conflict"):
            indexed_state(connection, env.store._deployment, env.binding)
