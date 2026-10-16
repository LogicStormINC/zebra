"""No-framework regression: failed savepoint cleanup must not replace the cause.

Run: uv run python scripts/check_projection_repair_cleanup.py
Native prefix/cancellation acceptance is separate; this forces rare cleanup faults.
"""

from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage.postgres.projection_work import (
    PostgresTaskProjectionWorkStore,
    _WorkConnection,
)
from psycopg.errors import InFailedSqlTransaction, QueryCanceled


def check(mode):
    class Connection:
        closed = False
        aborted = False
        commits = 0

        def __init__(self):
            self.statements = []
            self.primary = ValueError("invalid source header")
            self.cleanup = QueryCanceled("savepoint rollback timed out")

        def execute(self, statement, params=None):
            self.statements.append(statement)
            if statement.startswith("ROLLBACK TO SAVEPOINT"):
                if mode == "rollback":
                    raise self.cleanup
                self.aborted = False
            elif self.aborted:
                raise InFailedSqlTransaction("cleanup attempted in failed transaction")
            if statement.startswith("SELECT 128+"):
                self.aborted = True
                if mode == "source":
                    raise self.primary
                if mode == "socket":
                    self.closed = True
                    raise TimeoutError("native I/O expired")
                raise QueryCanceled("header statement timed out")
            if statement.startswith("RELEASE SAVEPOINT") and mode == "release":
                raise self.cleanup
            if statement == "COMMIT":
                if mode == "commit":
                    raise self.primary
                self.commits += 1
            if "FROM agent_tasks" in statement and statement.startswith("SELECT"):
                row = dict(next_event_sequence=1, event_position_state="ready",
                           selected_version="ag-ui-v1")
            elif statement.startswith("SELECT * FROM task_projection_work_routes"):
                row = dict(task_id=str(task), observed_through=-1,
                           wanted_through=0, needs_repair=1)
            else:
                row = {"enabled": 1}
            return SimpleNamespace(fetchone=lambda: row)

    task = uuid4()
    raw = Connection()
    bounded = _WorkConnection(raw, monotonic() + 2)
    store = object.__new__(PostgresTaskProjectionWorkStore)
    store._namespace, store._version = "cleanup-check", "ag-ui-v1"

    @contextmanager
    def connect(**kwargs):
        yield bounded
        bounded.commit()

    store._connect = connect
    try:
        store.repair_projection_work(task)
    except Exception as error:
        if mode in {"source", "commit"}:
            assert error is raw.primary, f"{mode}: original failure replaced by {error!r}"
        else:
            assert isinstance(error, CheckpointNotReady), (
                f"{mode}: deadline replaced by {type(error).__name__}: {error}"
            )
        if mode == "rollback":
            assert error.__cause__ is raw.cleanup
    else:
        raise AssertionError(f"{mode}: failed work was acknowledged")
    assert not any(s.startswith("RELEASE SAVEPOINT") for s in raw.statements), (
        f"{mode}: cleanup ran after header failure"
    )
    assert raw.commits == (2 if mode in {"query", "release"} else int(mode != "commit"))
    print(f"{mode}: primary preserved; failed work not acknowledged")


if __name__ == "__main__":
    for mode in ("rollback", "source", "socket", "query", "release", "commit"):
        check(mode)
