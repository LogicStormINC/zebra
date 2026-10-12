"""Client calls and actual libpq sockets, separately from server/trigger work.

Reuses the coverage profiler's reentrant Connection/Cursor guard. No SQL text,
parameters, identifiers, DSNs or generated content are retained in artifacts.
"""

from collections import Counter
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from threading import Lock
from time import perf_counter
from unittest.mock import patch

import psycopg
from agent_storage.postgres.database import PostgresDatabase
from psycopg_pool import ConnectionPool

LABEL = ContextVar("stream_baseline_label", default="setup")
_CHECKOUT = ContextVar("stream_baseline_checkout", default=False)
_INSIDE = ContextVar("stream_baseline_execute", default=False)


@contextmanager
def phase(name):
    token = LABEL.set(name)
    try:
        yield
    finally:
        LABEL.reset(token)


def category(query):
    text = str(query).lower()
    # Only bounded responsibility names are exported, never fingerprints or text.
    for name, needles in (
        ("lease", ("worker_leases", "control_plane_epochs")),
        ("checkpoint", ("projection_checkpoint", "projection_frames", "projection_cells")),
        ("progress", ("worker_progress",)),
        ("workspace", ("workspace_projections",)),
        ("session", ("session_projections",)),
        ("event", ("session_events", "session_streams")),
        ("task", ("agent_tasks", "execution_segments", "task_")),
        ("configuration", ("set_config", "discard all", "set ")),
    ):
        if any(needle in text for needle in needles):
            return name
    return "other"


class Telemetry:
    def __init__(self):
        self.calls = Counter()
        self.seconds = Counter()
        self.lock = Lock()
        self.stage = "initial"

    def increment(self, kind, value=1):
        key = f"{self.stage}/{LABEL.get()}/{kind}"
        with self.lock:
            self.calls[key] += value

    def measured(self, query, invoke):
        key = f"{self.stage}/{LABEL.get()}/sql:{category(query)}"
        operation = (str(query).lstrip().split(None, 1) or [""])[0].lower()
        self.increment(
            "statement:"
            + (
                operation
                if operation in {"select", "insert", "update", "delete", "with", "set"}
                else "other"
            )
        )
        started = perf_counter()
        token = _INSIDE.set(True)
        try:
            return invoke()
        finally:
            _INSIDE.reset(token)
            with self.lock:
                self.calls[key] += 1
                self.seconds[key] += perf_counter() - started

    @contextmanager
    def installed(self):
        execute = psycopg.Connection.execute
        cursor_execute = psycopg.Cursor.execute
        many = psycopg.Cursor.executemany
        connect_gen = psycopg.Connection._connect_gen.__func__
        checkout = PostgresDatabase.connect
        task_checkout = PostgresDatabase.connect_task_io
        commit = psycopg.Connection.commit
        rollback = psycopg.Connection.rollback
        pool_get = ConnectionPool.getconn

        def count(connection, query, *args, **kwargs):
            return self.measured(query, lambda: execute(connection, query, *args, **kwargs))

        def cursor_count(cursor, query, *args, **kwargs):
            def invoke():
                return cursor_execute(cursor, query, *args, **kwargs)

            return invoke() if _INSIDE.get() else self.measured(query, invoke)

        def many_count(cursor, query, *args, **kwargs):
            def invoke():
                return many(cursor, query, *args, **kwargs)

            return invoke() if _INSIDE.get() else self.measured(query, invoke)

        def sockets(cls, *args, **kwargs):
            result = yield from connect_gen(cls, *args, **kwargs)
            self.increment("new_pg_socket")
            return result

        def checkouts(database):
            self.increment("adapter_checkout")
            token = _CHECKOUT.set(True)
            try:
                return checkout(database)
            finally:
                _CHECKOUT.reset(token)

        def task_checkouts(database, *args, **kwargs):
            if not _CHECKOUT.get():
                self.increment("adapter_checkout")
            return task_checkout(database, *args, **kwargs)

        def pool_checkout(pool, *args, **kwargs):
            self.increment("pool_checkout")
            return pool_get(pool, *args, **kwargs)

        def committed(connection):
            self.increment("client_commit")
            return commit(connection)

        def rolled_back(connection):
            self.increment("client_rollback")
            return rollback(connection)

        with ExitStack() as stack:
            for target, name, replacement in (
                (psycopg.Connection, "execute", count),
                (psycopg.Cursor, "execute", cursor_count),
                (psycopg.Cursor, "executemany", many_count),
                (psycopg.Connection, "_connect_gen", classmethod(sockets)),
                (psycopg.Connection, "commit", committed),
                (psycopg.Connection, "rollback", rolled_back),
                (PostgresDatabase, "connect", checkouts),
                (PostgresDatabase, "connect_task_io", task_checkouts),
                (ConnectionPool, "getconn", pool_checkout),
            ):
                stack.enter_context(patch.object(target, name, replacement))
            yield self

    def report(self):
        return {
            "calls": dict(sorted(self.calls.items())),
            "db_seconds": dict(sorted(self.seconds.items())),
        }


def server_snapshot(dsn):
    with psycopg.connect(dsn, autocommit=True) as connection:
        rows = connection.execute(
            "SELECT toplevel,coalesce(sum(calls),0),coalesce(sum(total_exec_time),0) "
            "FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database "
            "WHERE datname=current_database()) "
            "AND query NOT LIKE '%%pg_stat_statements%%' "
            "AND query NOT LIKE '%%pg_current_wal_insert_lsn%%' GROUP BY toplevel"
        ).fetchall()
        wal = connection.execute("SELECT pg_current_wal_insert_lsn()::text").fetchone()[0]
    return {
        str(top): {"calls": int(calls), "milliseconds": float(ms)} for top, calls, ms in rows
    }, wal


def lsn_bytes(lsn):
    high, low = lsn.split("/")
    return (int(high, 16) << 32) + int(low, 16)
