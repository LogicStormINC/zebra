import os
from contextlib import contextmanager
from time import monotonic

import pytest
from agent_storage.postgres import connection_pool
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_io import task_io_deadline
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
