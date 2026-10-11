"""Native incremental accounting; independent scans and certification stay separate."""
# ruff: noqa: F811

import psycopg
import pytest
from agent_storage.postgres import coverage_model_index as index
from agent_storage.postgres.coverage_model_source import task_policy
from agent_storage.postgres.coverage_model_summary import summary_state
from agent_storage.postgres.coverage_model_summary_migration import (
    COVERAGE_MODEL_SUMMARY_MIGRATION as MIGRATION,
)

from tests.agent_storage.test_coverage_model_budget import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_env,
    postgres_dsn,
    reserve,
    spend,
    usage,
)
from tests.worker.coverage_model_cloud_fixtures import model_cloud  # noqa: F401
from tests.worker.test_coverage_model_acceptance import settled


class RollbackProbe(Exception):
    pass


def read(env, monkeypatch, expected):
    with env.store._database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, env.binding)
        assert policy is not None
        statements = []

        class BoundedRead:
            def execute(self, sql, args):
                statements.append(sql)
                assert "FROM coverage_model_summary" in sql, "historical scan on normal state"
                return connection.execute(sql, args)

        bounded = summary_state(BoundedRead(), NAMESPACE, env.binding, policy)
        assert bounded is not None
        assert (bounded.calls, bounded.charged_tokens, bounded.unresolved) == expected
        assert len(statements) == 1
        with monkeypatch.context() as legacy:
            legacy.setattr(index, "summary_state", lambda *args: None)
            assert index.indexed_state(
                connection, NAMESPACE, env.binding, _policy=policy,
            ) == bounded


def test_exact_incremental_reserve_first_settlement_and_retry(model_env, monkeypatch):
    env = model_env()
    request = reserve(env)
    read(env, monkeypatch, (0, 0, 0))
    assert spend(env, request).invoke
    read(env, monkeypatch, (1, 70, 1))
    assert not spend(env, request).invoke
    read(env, monkeypatch, (1, 70, 1))
    receipt = usage(env, request)
    first = env.store.record_model_usage(env.binding, receipt, fence=env.fence)
    read(env, monkeypatch, (1, receipt.total_tokens, 0))
    assert env.store.record_model_usage(env.binding, receipt, fence=env.fence) == first
    read(env, monkeypatch, (1, receipt.total_tokens, 0))


def test_unsupported_changes_disable_summary_and_rollback_restores(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    with env.store._database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, env.binding)
        before = summary_state(connection, NAMESPACE, env.binding, policy)
        assert before is not None
        for statement in (
            "UPDATE coverage_model_calls SET reserved_sequence=reserved_sequence+1",
            "UPDATE coverage_model_ledger SET charged_tokens=charged_tokens+1",
            "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
            "WHERE event_type='coverage_model_call_reserved'",
            "DELETE FROM coverage_model_events",
            "TRUNCATE coverage_model_calls",
        ):
            with pytest.raises(RollbackProbe), connection.transaction():
                connection.execute(statement)
                assert summary_state(connection, NAMESPACE, env.binding, policy) is None
                with pytest.raises(ValueError, match="model"):
                    index.indexed_state(connection, NAMESPACE, env.binding, _policy=policy)
                raise RollbackProbe
            assert summary_state(connection, NAMESPACE, env.binding, policy) == before
        for statement in (
            "UPDATE coverage_model_summary SET charged_tokens=0",
            "DELETE FROM coverage_model_summary",
            "TRUNCATE coverage_model_summary",
            "INSERT INTO coverage_model_summary (deployment_namespace,namespace,run_id) "
            "VALUES ('forged','forged','forged')",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="database maintained"):
                with connection.transaction():
                    connection.execute(statement)


def test_existing_history_is_not_upgraded_from_projection(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    with env.store._database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, env.binding)
        before = summary_state(connection, NAMESPACE, env.binding, policy)
        with pytest.raises(RollbackProbe), connection.transaction():
            # Administrative migration simulation ONLY in this fixture-owned schema.
            connection.execute("DROP TABLE coverage_model_summary CASCADE")
            connection.execute("DROP FUNCTION guard_coverage_model_summary() CASCADE")
            connection.execute("DROP FUNCTION advance_coverage_model_summary() CASCADE")
            for statement in MIGRATION.statements:
                connection.execute(statement)
            assert summary_state(connection, NAMESPACE, env.binding, policy) is None
            assert index.indexed_state(connection, NAMESPACE, env.binding, _policy=policy) == before
            raise RollbackProbe
        assert summary_state(connection, NAMESPACE, env.binding, policy) == before


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_admitted_normal_index_uses_one_exact_summary_read(model_cloud):
    env = model_cloud
    settled(env)
    with env.store._database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, env.binding)
        assert policy is not None
        statements = []

        class BoundedRead:
            def execute(self, sql, args):
                statements.append(sql)
                assert "FROM coverage_model_summary" in sql
                return connection.execute(sql, args)

        state = index.indexed_state(BoundedRead(), NAMESPACE, env.binding, _policy=policy)
        assert state.calls == 1 and state.unresolved == 0 and len(statements) == 1
        with pytest.raises(RollbackProbe), connection.transaction():
            connection.execute("DELETE FROM zebra_schema_migrations WHERE version=88")
            assert summary_state(connection, NAMESPACE, env.binding, policy) is None
            assert index.indexed_state(connection, NAMESPACE, env.binding, _policy=policy) == state
            raise RollbackProbe


def test_repaired_projection_never_requalifies_an_invalidated_summary(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    with env.store._database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, env.binding)
        expected = summary_state(connection, NAMESPACE, env.binding, policy)
        connection.execute("UPDATE coverage_model_ledger SET charged_tokens=charged_tokens+1")
        connection.execute("UPDATE coverage_model_ledger SET charged_tokens=charged_tokens-1")
        assert summary_state(connection, NAMESPACE, env.binding, policy) is None
        assert index.indexed_state(connection, NAMESPACE, env.binding, _policy=policy) == expected
