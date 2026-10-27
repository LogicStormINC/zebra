"""Explicit work units share one transaction and preserve isolation and failure."""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from time import monotonic

import pytest
from agent_storage.postgres.connection_scope import postgres_connection_scope
from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred
from agent_storage.postgres.database import PostgresDatabase, postgres_deadline
from agent_storage.postgres.work_unit import (
    borrow_work_unit,
    postgres_transaction_work_unit,
    postgres_work_unit,
)

from tests.worker.coverage_model_cloud_fixtures import dsn, postgres_dsn  # noqa: F401


def test_nested_reads_share_transaction_but_other_namespace_and_thread_do_not(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="one")
    other = PostgresDatabase(dsn, deployment_namespace="two")
    key = (dsn, "one")
    with postgres_connection_scope(), postgres_work_unit(database):
        with database.connect() as first:
            pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            first.execute("CREATE TEMP TABLE work_unit_probe(value integer)")
            with postgres_work_unit(database), database.connect() as second:
                assert second.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid
                second.execute("INSERT INTO work_unit_probe VALUES (3)")
            assert first.execute("SELECT value FROM work_unit_probe").fetchone()["value"] == 3
        with other.connect() as isolated:
            assert isolated.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid
        context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(context.run, borrow_work_unit, key).result() is None
            live = borrow_work_unit(key)
            with pytest.raises(RuntimeError, match="another thread"):
                executor.submit(lambda: live.execute("SELECT 1")).result()
            with pytest.raises(RuntimeError, match="another thread"):
                executor.submit(live.__enter__).result()
            assert live.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid
    with pytest.raises(RuntimeError, match="ended"):
        second.execute("SELECT 1")
    assert borrow_work_unit(key) is None


def test_caught_nested_error_still_rolls_back_entire_work_unit(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="test")
    with database.connect() as connection:
        connection.execute("CREATE TABLE work_unit_value(value integer)")
    with pytest.raises(RuntimeError, match="nested adapter failed"), postgres_work_unit(database):
        with database.connect() as connection:
            connection.execute("INSERT INTO work_unit_value VALUES (1)")
        try:
            with database.connect():
                raise ValueError("business refusal")
        except ValueError:
            pass
    with database.connect() as connection:
        assert not connection.execute("SELECT * FROM work_unit_value").fetchall()


def test_nested_adapter_cannot_commit_or_escape_tighter_deadline(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="test")
    with pytest.raises(RuntimeError, match="cannot end"), postgres_work_unit(database):
        with database.connect() as connection:
            connection.commit()
    with postgres_work_unit(database):
        with pytest.raises(CoverageRecoveryDeferred), postgres_deadline(monotonic() - 1):
            connection = database.connect()
            connection.execute("SELECT 1")


def test_adopted_transaction_reads_uncommitted_facts_and_only_outer_owner_commits(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="one")
    with database.connect() as connection:
        connection.execute("CREATE TABLE adopted_probe(value integer)")
    escaped = None
    with pytest.raises(ValueError, match="rollback outer"):
        with database.connect() as owner:
            owner.execute("INSERT INTO adopted_probe VALUES (7)")
            with postgres_transaction_work_unit(database, owner):
                with database.connect() as escaped:
                    row = escaped.execute("SELECT value FROM adopted_probe").fetchone()
                    assert row["value"] == 7
                    with pytest.raises(RuntimeError, match="cannot end"):
                        escaped.commit()
            raise ValueError("rollback outer")
    with database.connect() as connection:
        assert not connection.execute("SELECT * FROM adopted_probe").fetchall()
    with pytest.raises(RuntimeError, match="ended"):
        escaped.execute("SELECT 1")


def test_adopted_transaction_rejects_foreign_schema_and_poisoned_nested_reads(dsn):
    from psycopg.conninfo import make_conninfo

    database = PostgresDatabase(dsn, deployment_namespace="one")
    foreign = PostgresDatabase(
        make_conninfo(dsn, options="-c search_path=public"), deployment_namespace="one"
    )
    with database.connect() as owner:
        with pytest.raises(ValueError, match="another database or schema"):
            with postgres_transaction_work_unit(foreign, owner):
                pytest.fail("borrowed foreign schema")
        with pytest.raises(RuntimeError, match="nested adapter failed"):
            with postgres_transaction_work_unit(database, owner):
                try:
                    with database.connect():
                        raise ValueError("refused")
                except ValueError:
                    pass


def test_adoption_keeps_direct_connection_deadline_and_rejects_other_options(dsn):
    from psycopg.conninfo import make_conninfo

    database = PostgresDatabase(dsn, deployment_namespace="one")
    with postgres_deadline(monotonic() + 20), database.connect() as owner:
        with postgres_transaction_work_unit(database, owner), database.connect() as nested:
            assert nested.execute("SELECT pg_backend_pid() AS pid").fetchone() == (
                owner.execute("SELECT pg_backend_pid() AS pid").fetchone()
            )
            with pytest.raises(CoverageRecoveryDeferred), postgres_deadline(monotonic() - 1):
                database.connect().execute("SELECT 1")
    foreign = PostgresDatabase(
        make_conninfo(dsn, options="-c search_path=public"), deployment_namespace="one"
    )
    with postgres_deadline(monotonic() + 20), foreign.connect() as owner:
        with pytest.raises(ValueError, match="another database or schema"):
            with postgres_transaction_work_unit(database, owner):
                pytest.fail("deadline suffix hid a different search path")


def test_exact_owner_reentry_shares_transaction_and_rejects_second_socket(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="one")
    with database.connect() as connection:
        connection.execute("CREATE TABLE reentry_probe(value integer)")
    with postgres_connection_scope(), postgres_work_unit(database):
        with database.connect() as owner:
            owner.execute("INSERT INTO reentry_probe VALUES (11)")
            with postgres_transaction_work_unit(database, owner), database.connect() as reader:
                assert reader.execute("SELECT value FROM reentry_probe").fetchone()["value"] == 11
                assert reader.execute("SELECT pg_backend_pid() AS pid").fetchone() == (
                    owner.execute("SELECT pg_backend_pid() AS pid").fetchone()
                )
            # A same-DSN independent socket is not the owner, even if its libpq
            # parameters match. No transaction replacement or split commit.
            import psycopg

            with psycopg.connect(dsn) as foreign:
                with pytest.raises(RuntimeError, match="already has an owner"):
                    with postgres_transaction_work_unit(database, foreign):
                        pytest.fail("adopted a second socket")
        with database.connect() as after:
            assert after.execute("SELECT value FROM reentry_probe").fetchone()["value"] == 11
    with pytest.raises(RuntimeError, match="ended"):
        reader.execute("SELECT 1")


def test_caught_reentry_failure_poisons_the_outer_transaction(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="one")
    with database.connect() as connection:
        connection.execute("CREATE TABLE reentry_failure(value integer)")
    with pytest.raises(RuntimeError, match="nested adapter failed"):
        with postgres_work_unit(database), database.connect() as owner:
            owner.execute("INSERT INTO reentry_failure VALUES (1)")
            try:
                with postgres_transaction_work_unit(database, owner):
                    raise ValueError("nested refusal")
            except ValueError:
                pass
    with database.connect() as connection:
        assert not connection.execute("SELECT * FROM reentry_failure").fetchall()


def test_deadline_wrapped_owner_reentry_keeps_tighter_budget(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="one")
    with postgres_deadline(monotonic() + 20), postgres_work_unit(database):
        with database.connect() as owner:
            with postgres_transaction_work_unit(database, owner), database.connect() as reader:
                assert reader.execute("SELECT pg_backend_pid() AS pid").fetchone() == (
                    owner.execute("SELECT pg_backend_pid() AS pid").fetchone()
                )
                with pytest.raises(CoverageRecoveryDeferred), postgres_deadline(monotonic() - 1):
                    database.connect().execute("SELECT 1")


def test_positive_nested_deadline_cancels_before_the_owner_timeout(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="one")
    with database.connect() as connection:
        connection.execute("CREATE TABLE deadline_rollback(value integer)")
    with pytest.raises(CoverageRecoveryDeferred, match="database proof deadline exhausted"):
        with postgres_deadline(monotonic() + 20), postgres_work_unit(database):
            with database.connect() as owner, postgres_transaction_work_unit(database, owner):
                owner.execute("INSERT INTO deadline_rollback VALUES (7)")
                started = monotonic()
                with postgres_deadline(started + 0.2), database.connect() as nested:
                    try:
                        nested.execute("SELECT pg_sleep(3)")
                    finally:
                        # A post-query deadline refusal after the full 3s is not
                        # sufficient: the server itself must cancel the query.
                        assert monotonic() - started < 2
    assert borrow_work_unit((dsn, "one")) is None
    with database.connect() as connection:
        assert not connection.execute("SELECT * FROM deadline_rollback").fetchall()
        assert connection.execute("SELECT 1 AS ready").fetchone()["ready"] == 1


def test_native_task_io_owner_is_adopted_without_dropping_option_isolation(dsn):
    from agent_storage.postgres.task_io import TaskIoConnection, TaskIoConnections

    database = PostgresDatabase(dsn, deployment_namespace="native-publication")
    with TaskIoConnections(dsn).connect(deadline=monotonic() + 5) as owner:
        assert isinstance(owner, TaskIoConnection)
        with postgres_transaction_work_unit(database, owner), database.connect() as nested:
            assert (
                nested.execute("SELECT pg_backend_pid() AS pid").fetchone()
                == owner.execute("SELECT pg_backend_pid() AS pid").fetchone()
            )
