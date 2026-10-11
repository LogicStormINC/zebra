"""Physical reuse preserves separate transactions, freshness and scoped cleanup."""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from time import monotonic

import psycopg
import pytest
from agent_storage.postgres.connection_scope import (
    current_connection_scope,
    postgres_connection_scope,
)
from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred
from agent_storage.postgres.database import PostgresDatabase, postgres_deadline

from tests.worker.coverage_model_cloud_fixtures import dsn, postgres_dsn  # noqa: F401


def test_scope_nested_and_copied_thread_context_do_not_share():
    assert current_connection_scope() is None
    with postgres_connection_scope():
        owner = current_connection_scope()
        with postgres_connection_scope():
            assert current_connection_scope() is owner
        context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(context.run, current_connection_scope).result() is None
    assert current_connection_scope() is None
    assert owner.closed


@pytest.mark.parametrize("failure", [None, "business", "commit"])
def test_reset_failure_preserves_committed_success_or_original_exception(monkeypatch, failure):
    class Connection:
        closed = False
        committed = False
        rolled_back = False

        def commit(self):
            if failure == "commit":
                raise RuntimeError("commit failed")
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def execute(self, sql):
            assert sql == "DISCARD ALL"
            raise OSError("reset transport failed")

        def close(self):
            self.closed = True

    raw = Connection()
    monkeypatch.setattr("agent_storage.postgres.database.psycopg.connect", lambda *_a, **_k: raw)
    database = PostgresDatabase("postgresql://localhost/test", deployment_namespace="test")
    original = ValueError("business refusal")
    with postgres_connection_scope():
        if failure == "business":
            with pytest.raises(ValueError) as raised, database.connect():
                raise original
            assert raised.value is original and raw.rolled_back and not raw.committed
        elif failure == "commit":
            with pytest.raises(RuntimeError, match="commit failed"), database.connect():
                pass
            assert not raw.committed
        else:
            with database.connect():
                pass
            assert raw.committed
        assert raw.closed and not any(current_connection_scope().idle.values())
        assert not current_connection_scope().connections


def test_native_reuse_transaction_reset_freshness_and_namespace(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="test")
    other = PostgresDatabase(dsn, deployment_namespace="other")
    with database.connect() as conn:
        conn.execute("CREATE TABLE scoped_value (value integer)")
        conn.execute("INSERT INTO scoped_value VALUES (1)")
    with postgres_connection_scope():
        with database.connect() as first:
            raw = first.connection
            pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            first.execute("SET statement_timeout='12345ms'")
            first.execute("CREATE TEMP TABLE private_temporary (value integer)")
            with database.connect() as nested:
                assert nested.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid
        with other.connect() as separate:
            assert separate.connection is not raw
        with database.connect() as reused:
            assert reused.connection is raw
            assert reused.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "0"
            temporary = reused.execute("SELECT to_regclass('private_temporary') AS t").fetchone()
            assert temporary["t"] is None
            # An independent writer is visible on the next statement, no saved authority rows.
            with psycopg.connect(dsn) as independent:
                independent.execute("UPDATE scoped_value SET value=2")
            assert reused.execute("SELECT value FROM scoped_value").fetchone()["value"] == 2
        with pytest.raises(RuntimeError, match="borrow has ended"):
            reused.execute("SELECT 1")
        with pytest.raises(ValueError, match="rollback"), database.connect() as failed:
            failed.execute("UPDATE scoped_value SET value=3")
            raise ValueError("rollback")
        with database.connect() as recovered:
            assert recovered.execute("SELECT value FROM scoped_value").fetchone()["value"] == 2
        with database.connect() as explicit:
            explicit.close()
        with database.connect() as after_closed:
            assert not after_closed.closed
    assert raw.closed and after_closed.connection.closed


def test_native_deadline_is_fresh_after_reuse_and_resets(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="test")
    with postgres_connection_scope():
        with postgres_deadline(monotonic() + 10), database.connect() as connection:
            raw = connection.connection.connection
            connection.execute("SELECT 1")
        with postgres_deadline(monotonic() - 1), pytest.raises(CoverageRecoveryDeferred):
            database.connect()
        with database.connect() as ordinary:
            assert ordinary.connection is raw
            assert ordinary.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "0"
        with pytest.raises(CoverageRecoveryDeferred), postgres_deadline(monotonic() + 10):
            with database.connect() as expiring:
                expiring.deadline = monotonic() - 1
        with database.connect() as recovered:
            assert recovered.execute("SELECT 1 AS value").fetchone()["value"] == 1


def test_native_failed_callback_closes_even_unreturned_connection(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="test")
    with pytest.raises(ValueError, match="callback"), postgres_connection_scope():
        outstanding = database.connect()
        outstanding.execute("CREATE TEMP TABLE private_abort (value integer)")
        raise ValueError("callback")
    assert outstanding.connection.closed
