import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from time import monotonic

import psycopg
import pytest
from agent_storage.postgres import connection_pool
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_io import task_io_deadline
from psycopg import IsolationLevel
from psycopg.pq import TransactionStatus


class FakePool:
    check_connection = staticmethod(lambda connection: None)

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, dsn, **kwargs):
        self.options = kwargs
        self.closed = False
        self.requests = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    @contextmanager
    def connection(self):
        self.requests += 1
        yield "pooled connection"


def test_pool_is_explicit_bounded_dsn_specific_and_closed(monkeypatch):
    monkeypatch.setattr(connection_pool, "ConnectionPool", FakePool)
    assert connection_pool.composition_pool("dbname=one") is None
    with connection_pool.postgres_pool_scope("dbname=one"):
        database = PostgresDatabase("dbname=one", deployment_namespace="one")
        pool = database._pool
        assert pool.options["max_size"] == 8 and pool.options["timeout"] == 2
        assert PostgresDatabase("dbname=two", deployment_namespace="two")._pool is None
        with database.connect() as connection:
            assert connection == "pooled connection"
        assert pool.requests == 1
    assert pool.closed
    assert connection_pool.composition_pool("dbname=one") is None


def test_bounded_io_never_uses_the_ordinary_pool(monkeypatch):
    monkeypatch.setattr(connection_pool, "ConnectionPool", FakePool)
    with connection_pool.postgres_pool_scope("dbname=one"):
        database = PostgresDatabase("dbname=one", deployment_namespace="one")
        monkeypatch.setattr(database, "connect_task_io", lambda **kwargs: "bounded fresh")
        with task_io_deadline(monotonic() + 1):
            assert database.connect() == "bounded fresh"
        assert database._pool.requests == 0


def test_nested_scope_and_exception_restore_the_outer_binding(monkeypatch):
    monkeypatch.setattr(connection_pool, "ConnectionPool", FakePool)
    with connection_pool.postgres_pool_scope("dbname=one"):
        outer = connection_pool.composition_pool("dbname=one")
        try:
            with connection_pool.postgres_pool_scope("dbname=two"):
                assert connection_pool.composition_pool("dbname=one") is None
                raise RuntimeError("exit")
        except RuntimeError:
            pass
        assert connection_pool.composition_pool("dbname=one") is outer


def test_real_pool_reuses_connection_and_rolls_back_on_failure():
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for real pool acceptance")
    with connection_pool.postgres_pool_scope(dsn):
        database = PostgresDatabase(dsn, deployment_namespace="pool-read-only-smoke")
        database._pool.resize(1, 1)
        database._pool.wait()
        with database.connect() as connection:
            pid = connection.info.backend_pid
            assert connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
        with pytest.raises(ValueError, match="rollback"):
            with database.connect() as connection:
                connection.execute("SELECT set_config('application_name', 'pool-rollback', true)")
                raise ValueError("rollback")
        with database.connect() as connection:
            assert connection.info.transaction_status is TransactionStatus.IDLE
            assert connection.info.backend_pid == pid
            name = connection.execute("SHOW application_name").fetchone()["application_name"]
            assert name != "pool-rollback"


@pytest.mark.parametrize("failed", [False, True])
def test_real_pool_reader_defaults_do_not_poison_next_writer(failed):
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for real pool acceptance")
    with connection_pool.postgres_pool_scope(dsn):
        database = PostgresDatabase(dsn, deployment_namespace="pool-reader-writer")
        database._pool.resize(1, 1)
        database._pool.wait()
        try:
            with database.connect() as connection:
                pid = connection.info.backend_pid
                connection.isolation_level = IsolationLevel.REPEATABLE_READ
                connection.read_only = True
                connection.deferrable = True
                assert connection.execute("SHOW transaction_read_only").fetchone()[
                    "transaction_read_only"
                ] == "on"
                if failed:
                    raise ValueError("reader failed")
        except ValueError:
            assert failed
        with database.connect() as connection:
            assert connection.info.backend_pid == pid
            assert connection.isolation_level is None
            assert connection.read_only is None
            assert connection.deferrable is None
            assert not connection.autocommit
            connection.execute("CREATE TEMP TABLE pool_writable (value integer) ON COMMIT DROP")
            connection.execute("INSERT INTO pool_writable VALUES (1)")
            assert connection.execute("SELECT value FROM pool_writable").fetchone()["value"] == 1


def test_real_reset_restores_autocommit_without_sql_and_discards_failed_reset(monkeypatch):
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for real pool acceptance")
    with psycopg.connect(dsn) as connection:
        connection.autocommit = True
        connection.read_only = True
        with monkeypatch.context() as patch:
            def forbidden(*args, **kwargs):
                raise AssertionError("reset added SQL")

            patch.setattr(psycopg.Connection, "execute", forbidden)
            connection_pool._reset_transaction_defaults(connection)
        assert connection.read_only is None and not connection.autocommit

    reset = connection_pool._reset_transaction_defaults

    def unavailable(connection):
        if connection.read_only:
            raise psycopg.OperationalError("synthetic reset failure")
        reset(connection)

    monkeypatch.setattr(connection_pool, "_reset_transaction_defaults", unavailable)
    with connection_pool.postgres_pool_scope(dsn):
        database = PostgresDatabase(dsn, deployment_namespace="pool-reset-fault")
        database._pool.resize(1, 1)
        database._pool.wait()
        with database.connect() as connection:
            pid = connection.info.backend_pid
            connection.read_only = True
        with database.connect() as replacement:
            assert replacement.info.backend_pid != pid
            assert replacement.read_only is None
            replacement.execute(
                "CREATE TEMP TABLE reset_replacement (value integer) ON COMMIT DROP"
            )


def test_real_shared_pool_readers_and_writers_are_safe_across_worker_threads():
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for real pool acceptance")
    with connection_pool.postgres_pool_scope(dsn):
        # Composition captures the pool before handing adapters to Worker threads.
        databases = [PostgresDatabase(dsn, deployment_namespace=f"pool-thread-{n}")
                     for n in range(4)]

        def cycle(database):
            for _ in range(8):
                with database.connect() as reader:
                    reader.isolation_level = IsolationLevel.REPEATABLE_READ
                    reader.read_only = True
                    assert reader.execute("SHOW transaction_read_only").fetchone()[
                        "transaction_read_only"
                    ] == "on"
                with database.connect() as writer:
                    assert writer.read_only is None and writer.isolation_level is None
                    writer.execute("CREATE TEMP TABLE pool_thread_write (value int) ON COMMIT DROP")
                    writer.execute("INSERT INTO pool_thread_write VALUES (1)")
            return True

        with ThreadPoolExecutor(max_workers=4) as workers:
            assert all(workers.map(cycle, databases))
