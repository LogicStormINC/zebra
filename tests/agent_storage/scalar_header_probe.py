"""Cold-process Header SQL probes; no application DB or event hydration."""

import argparse
import ctypes
import ctypes.util
import json
import sqlite3
import time
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_storage.task_replay_headers import read_event_header, read_run_header


def sqlite_visits(path: Path, statement: str) -> dict:
    library = ctypes.CDLL(ctypes.util.find_library("sqlite3"))
    library.sqlite3_open_v2.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
    ]
    library.sqlite3_prepare_v2.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    library.sqlite3_step.argtypes = [ctypes.c_void_p]
    library.sqlite3_stmt_status.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    library.sqlite3_finalize.argtypes = [ctypes.c_void_p]
    library.sqlite3_close.argtypes = [ctypes.c_void_p]
    library.sqlite3_libversion.restype = ctypes.c_char_p
    handle, prepared = ctypes.c_void_p(), ctypes.c_void_p()
    assert library.sqlite3_open_v2(str(path).encode(), ctypes.byref(handle), 1, None) == 0
    try:
        assert (
            library.sqlite3_prepare_v2(handle, statement.encode(), -1, ctypes.byref(prepared), None)
            == 0
        )
        result = library.sqlite3_step(prepared)
        while result == 100:  # SQLITE_ROW
            result = library.sqlite3_step(prepared)
        assert result == 101  # SQLITE_DONE
        metrics = {
            "vm_steps": library.sqlite3_stmt_status(prepared, 4, 0),
            "fullscan_steps": library.sqlite3_stmt_status(prepared, 1, 0),
            "scanstatus_sqlite": library.sqlite3_libversion().decode(),
            "visits": None,
        }
        if hasattr(library, "sqlite3_stmt_scanstatus"):
            library.sqlite3_stmt_scanstatus.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_void_p,
            ]
            index, visits = 0, []
            count = ctypes.c_int64()
            while library.sqlite3_stmt_scanstatus(prepared, index, 1, ctypes.byref(count)) == 0:
                visits.append(count.value)
                index += 1
            if visits:
                metrics["visits"] = visits
        return metrics
    finally:
        if prepared.value:
            library.sqlite3_finalize(prepared)
        library.sqlite3_close(handle)


def sqlite_probe(path: Path, task_id: TaskId, count: int) -> dict:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    statements, steps = [], [0]

    def authorize(action, first, second, *_):
        if action == sqlite3.SQLITE_READ and first == "session_events" and second == "payload":
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(second).startswith("json"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)
    connection.set_trace_callback(statements.append)
    connection.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
    started = time.perf_counter()
    assert read_event_header(connection, task_id, count - 1).command_kind is None
    latest = read_run_header(connection, task_id, "latest", None)
    assert latest.start == count // 2 and latest.stop is None
    assert read_run_header(connection, task_id, "run-0", None).stop == 1
    assert read_run_header(connection, task_id, "control-only", None).control_only
    assert read_run_header(connection, task_id, "missing", None).anchor is None
    milliseconds = (time.perf_counter() - started) * 1000
    connection.set_progress_handler(None, 0)
    connection.set_trace_callback(None)
    metrics = []
    for statement in statements:
        plan = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + statement)]
        metrics.append({"sql": statement, "plan": plan, **sqlite_visits(path, statement)})
    connection.close()
    return {
        "milliseconds": milliseconds,
        "python_vm_steps": steps[0],
        "python_sqlite": sqlite3.sqlite_version,
        "decoded_body_bytes": 0,
        "queries": metrics,
    }


def postgres_probe(dsn: str, task_id: TaskId, count: int, role: str) -> dict:
    import psycopg
    from agent_storage.postgres.task_replay_headers import (
        read_event_header as pg_event,
    )
    from agent_storage.postgres.task_replay_headers import (
        read_run_header as pg_run,
    )
    from psycopg import sql
    from psycopg.rows import dict_row

    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        metrics = []

        class MeasuredConnection:
            def execute(self, statement, parameters):
                cursor = connection.execute(statement, parameters)
                plan = connection.execute(
                    "EXPLAIN (ANALYZE,BUFFERS,VERBOSE,FORMAT JSON) " + statement, parameters
                ).fetchone()["QUERY PLAN"][0]
                metrics.append({"sql": statement, "plan": plan})
                return cursor

        measured = MeasuredConnection()
        started = time.perf_counter()
        assert pg_event(measured, "header-probe", task_id, count - 1).command_kind is None
        latest = pg_run(measured, "header-probe", task_id, "latest", None)
        assert latest.start == count // 2 and latest.stop is None
        assert pg_run(measured, "header-probe", task_id, "run-0", None).stop == 1
        assert pg_run(measured, "header-probe", task_id, "control-only", None).control_only
        assert pg_run(measured, "header-probe", task_id, "missing", None).anchor is None
        return {
            "milliseconds_including_explain": (time.perf_counter() - started) * 1000,
            "decoded_body_bytes": 0,
            "queries": metrics,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("sqlite", "postgres"))
    parser.add_argument("target")
    parser.add_argument("task_id")
    parser.add_argument("count", type=int)
    parser.add_argument("--role", default="")
    args = parser.parse_args()
    task = TaskId(UUID(args.task_id))
    result = (
        sqlite_probe(Path(args.target), task, args.count)
        if args.backend == "sqlite"
        else postgres_probe(args.target, task, args.count, args.role)
    )
    print(json.dumps(result))
