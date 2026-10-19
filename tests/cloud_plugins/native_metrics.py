"""One bounded driver counter, shared by the fixed direct/Plugin workload."""

from contextlib import contextmanager
from threading import Lock, local
from time import monotonic
from unittest.mock import patch

import psycopg
from agent_storage.postgres.task_io import TaskIoConnections


@contextmanager
def measured(rows, *, arm, phase, temperature):
    row = dict(
        arm=arm,
        phase=phase,
        temperature=temperature,
        attempted_driver_sql=0,
        reset_sql=0,
        physical_connects=0,
    )
    lock, nesting = Lock(), local()
    original_open = TaskIoConnections._open
    original_connect = psycopg.connect

    def connect(*args, **kwargs):
        with lock:
            row["physical_connects"] += 1
        return original_connect(*args, **kwargs)

    def opened(self, *args, **kwargs):
        with lock:
            row["physical_connects"] += 1
        return original_open(self, *args, **kwargs)

    def wrap(original):
        def execute(self, query, *args, **kwargs):
            depth = getattr(nesting, "depth", 0)
            nesting.depth = depth + 1
            try:
                return original(self, query, *args, **kwargs)
            finally:
                nesting.depth = depth
                if depth == 0:
                    key = (
                        "reset_sql"
                        if str(query).strip().upper() == "DISCARD ALL"
                        else "attempted_driver_sql"
                    )
                    with lock:
                        row[key] += 1

        return execute

    start = monotonic()
    with (
        patch.object(psycopg, "connect", connect),
        patch.object(TaskIoConnections, "_open", opened),
        patch.object(psycopg.Cursor, "execute", wrap(psycopg.Cursor.execute)),
        patch.object(psycopg.ClientCursor, "execute", wrap(psycopg.ClientCursor.execute)),
    ):
        yield row
    row["elapsed_ms"] = round((monotonic() - start) * 1000, 3)
    rows.append(row)
