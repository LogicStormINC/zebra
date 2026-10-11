"""Cold-process scalar queue probes; these are not live latency/P95 claims."""

import argparse
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import psycopg
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projection_work import HEADER_BYTES as PG_BYTES
from agent_storage.postgres.projection_work import PG_PENDING, PostgresTaskProjectionWorkStore
from agent_storage.projection_work import SQLiteTaskProjectionWorkStore
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from tests.agent_storage.scalar_header_probe import sqlite_visits


def sqlite_probe(path, task, namespace, count):
    statements, writes = [], []
    store = SQLiteTaskProjectionWorkStore(path, namespace, "ag-ui-v1")
    original = store._connect

    @contextmanager
    def connect(**kwargs):
        with original(**kwargs) as connection:

            def authorize(action, table, column, *_):
                if (
                    action == sqlite3.SQLITE_READ
                    and table == "session_events"
                    and column == "payload"
                ):
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_FUNCTION and str(column).startswith("json"):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            connection.set_trace_callback(statements.append)
            before = connection.total_changes
            yield connection
            if not kwargs.get("write"):
                assert connection.total_changes == before
                writes.append(0)

    store._connect = connect
    started = time.perf_counter()
    pending = store.read_pending_projection_work()
    assert len(pending) == 32
    assert store.read_pending_projection_work(after_scope=pending[-1].scope) == ()
    assert len(store.read_projection_work_repairs()) == 1
    assert not store.repair_projection_work(task, limit=1).needs_repair
    pending = store.read_pending_projection_work()
    latest = max(pending, key=lambda w: w.anchor_sequence)
    assert latest.requested_through == count - 1
    assert store.read_projection_work_problem(latest.scope) is None
    elapsed = (time.perf_counter() - started) * 1000
    selects = sorted(set(s for s in statements if s.lstrip().upper().startswith("SELECT")))
    plans, visits = [], []
    with sqlite3.connect(path) as connection:
        for statement in selects:
            plans.extend(r[3] for r in connection.execute("EXPLAIN QUERY PLAN " + statement))
            measured = sqlite_visits(Path(path), statement)
            assert measured["fullscan_steps"] == 0, (statement, measured)
            if measured["visits"]:
                assert max(measured["visits"]) <= 32, (statement, measured)
            visits.append(measured)
    assert any("session_events_scalar_header" in p for p in plans)
    assert any("projection_work_pending" in p for p in plans)
    return dict(
        count=count,
        elapsed_ms=round(elapsed, 3),
        readonly_reads=len(writes),
        payload_denied=True,
        plans=plans,
        visits=visits,
    )


def nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from nodes(child)


def pg_probe(dsn, task, namespace, count):
    configured = conninfo_to_dict(dsn)
    assert configured["host"] in ("127.0.0.1", "localhost")
    assert configured["dbname"] == "header_scratch"
    store = PostgresTaskProjectionWorkStore(
        PostgresDatabase(dsn, deployment_namespace=namespace), "ag-ui-v1"
    )
    started = time.perf_counter()
    pending = store.read_pending_projection_work()
    assert len(pending) == 32
    assert store.read_pending_projection_work(after_scope=pending[-1].scope) == ()
    assert len(store.read_projection_work_repairs()) == 1
    assert not store.repair_projection_work(task, limit=1).needs_repair
    latest = max(store.read_pending_projection_work(), key=lambda w: w.anchor_sequence)
    assert latest.requested_through == count - 1
    assert store.read_projection_work_problem(latest.scope) is None
    elapsed = (time.perf_counter() - started) * 1000
    queries = (
        (PG_PENDING, (namespace, "ag-ui-v1", "", "", 32)),
        (PG_PENDING, (namespace, "ag-ui-v1", str(task), str(latest.scope.anchor_event_id), 32)),
        (
            f"SELECT {PG_BYTES},replay_header_ready FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s",
            (namespace, task, count - 1),
        ),
        (
            "SELECT task_id,observed_through,wanted_through FROM task_projection_work_routes "
            "WHERE deployment_namespace=%s AND projector_version=%s AND needs_repair=1 "
            "AND task_id>%s ORDER BY task_id LIMIT %s",
            (namespace, "ag-ui-v1", "", 32),
        ),
    )
    plans = []
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL enable_bitmapscan=off")
        connection.execute("SET LOCAL enable_seqscan=off")
        assert (
            connection.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]
            == "on"
        )
        for statement, params in queries:
            plan = connection.execute(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + statement, params
            ).fetchone()["QUERY PLAN"][0]["Plan"]
            flattened = list(nodes(plan))
            for node in flattened:
                assert node["Actual Rows"] * node["Actual Loops"] <= 32, node
                assert node.get("Rows Removed by Filter", 0) == 0, node
                if node.get("Relation Name") in ("session_events", "task_projection_work"):
                    assert node["Node Type"] != "Seq Scan", node
            plans.append(flattened)
        with connection.transaction(force_rollback=True):
            try:
                connection.execute("SELECT payload FROM session_events LIMIT 1")
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError("probe role could read bodies")
    return dict(count=count, elapsed_ms=round(elapsed, 3), payload_denied=True, plans=plans)


def bootstrap_probe(backend, location, namespace, count):
    store = (
        SQLiteTaskProjectionWorkStore(location, namespace, "ag-ui-v1")
        if backend == "sqlite"
        else PostgresTaskProjectionWorkStore(
            PostgresDatabase(location, deployment_namespace=namespace), "ag-ui-v1"
        )
    )
    original, statements = store._connect, []

    @contextmanager
    def connect(**kwargs):
        with original(**kwargs) as connection:
            if backend == "sqlite":
                connection.set_authorizer(
                    lambda action, table, column, *_: sqlite3.SQLITE_DENY
                    if (action == sqlite3.SQLITE_READ and table == "session_events")
                    or (action == sqlite3.SQLITE_FUNCTION and str(column).startswith("json"))
                    else sqlite3.SQLITE_OK
                )
                connection.set_trace_callback(lambda query: statements.append((query, None)))
            else:
                execute = connection.execute

                def record(query, params=None):
                    statements.append((query, params))
                    return execute(query, params)

                connection.execute = record
            yield connection

    store._connect = connect
    started = time.perf_counter()
    assert not store.bootstrap_projection_work()
    assert store.bootstrap_projection_work()
    before = len(statements)
    assert store.bootstrap_projection_work()
    assert not any("FROM agent_tasks" in query for query, _ in statements[before:])
    elapsed = (time.perf_counter() - started) * 1000
    queries = [(query, params) for query, params in statements if "FROM agent_tasks" in query]
    assert len(queries) == 2
    visits, plans = [], []
    if backend == "sqlite":
        for query, _ in queries:
            measured = sqlite_visits(Path(location), query)
            assert measured["fullscan_steps"] == 0
            assert max(measured["visits"]) <= 32
            visits.append(measured)
    else:
        with psycopg.connect(location, row_factory=dict_row) as connection:
            # Explicit bootstrap locks only bounded Task HWM rows. Unlike pending
            # observation above, its actual FOR SHARE plan is not a READ ONLY query.
            connection.execute("SET LOCAL enable_bitmapscan=off")
            connection.execute("SET LOCAL enable_seqscan=off")
            for query, params in queries:
                plan = connection.execute(
                    "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query, params
                ).fetchone()["QUERY PLAN"][0]["Plan"]
                flattened = list(nodes(plan))
                for node in flattened:
                    assert node["Actual Rows"] * node["Actual Loops"] <= 32
                    assert node.get("Rows Removed by Filter", 0) == 0
                    assert node["Node Type"] not in ("Seq Scan", "Bitmap Heap Scan")
                plans.append(flattened)
    return dict(count=count, elapsed_ms=round(elapsed, 3), visits=visits, plans=plans)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("sqlite", "postgres"))
    parser.add_argument("location")
    parser.add_argument("task")
    parser.add_argument("namespace")
    parser.add_argument("count", type=int)
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    task = TaskId(UUID(args.task))
    result = (
        bootstrap_probe(args.backend, args.location, args.namespace, args.count)
        if args.bootstrap
        else (
            sqlite_probe(args.location, task, args.namespace, args.count)
            if args.backend == "sqlite"
            else pg_probe(args.location, task, args.namespace, args.count)
        )
    )
    print(json.dumps(result))
