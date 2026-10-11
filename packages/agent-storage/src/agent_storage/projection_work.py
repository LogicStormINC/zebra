"""SQLite durable derived-work queue. Constructors and reads never repair."""

import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import EventId, TaskId
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionScope,
)
from agent_core.ports.task_projection_work import (
    MAX_ENABLED_PROJECTORS,
    MAX_PROJECTION_WORK_BYTES,
    PROJECTION_PROBLEM_CODES,
    PROJECTION_WORK_SECONDS,
    ProjectionWork,
    ProjectionWorkProblem,
    ProjectionWorkRepair,
    TaskProjectionWorkPort,
)

from agent_storage.projection_work_routing import (
    BOOTSTRAP_SOURCE,
    COVERAGE,
    ORDINARY,
    activate_privacy,
    classified_pending,
    routed_statements,
    task_version,
)
from agent_storage.projection_work_routing import PENDING as PENDING
from agent_storage.projection_work_schema import SOURCE

WHERE = "deployment_namespace=? AND task_id=? AND anchor_key=? AND projector_version=?"
HEADER_BYTES = "128+" + "+".join(
    f"COALESCE(length(CAST({name} AS BLOB)),0)"
    for name in ("event_id", "event_type", "replay_command_kind", "replay_run_id")
)


def checked_limit(limit: int, maximum: int = 32) -> int:
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise ValueError("invalid projection-work page limit")
    return limit


def scope_values(scope: ProjectionScope) -> tuple[str, str, str, str]:
    return (
        scope.namespace,
        str(scope.task_id),
        str(scope.anchor_event_id or ""),
        scope.projector_version,
    )


def work_from_row(row: Mapping[str, Any]) -> ProjectionWork:
    return ProjectionWork(
        ProjectionScope(
            row["deployment_namespace"],
            TaskId(UUID(str(row["task_id"]))),
            EventId(UUID(row["anchor_key"])),
            row["projector_version"],
        ),
        row["run_id"],
        row["anchor_sequence"],
        row["requested_through"],
        row["revision"],
        row["after_sequence"],
        row["closed_through"],
    )


def retry_delay(code: str, seconds: float | None) -> float | None:
    if code not in PROJECTION_PROBLEM_CODES:
        raise ValueError("invalid redacted projection-work problem code")
    if seconds is not None and (type(seconds) not in (int, float) or not 1 <= seconds <= 3600):
        raise ValueError("retry delay must be between 1 and 3600 seconds")
    if code == "integrity" and seconds is not None:
        raise ValueError("integrity requires explicit operator repair/retry")
    return None if seconds is None else float(seconds)


class SQLiteTaskProjectionWorkStore(TaskProjectionWorkPort):
    def __init__(self, database_path: str | Path, namespace: str, projector_version: str) -> None:
        ProjectionScope(namespace, TaskId(UUID(int=0)), None, projector_version)
        self._path = Path(database_path).absolute()
        self._namespace = namespace
        self._version = projector_version

    @contextmanager
    def _connect(
        self, *, write: bool = False, deadline: float | None = None
    ) -> Iterator[sqlite3.Connection]:
        # ponytail: no schema bootstrap or file creation; the composition root installs DDL.
        deadline = time.monotonic() + PROJECTION_WORK_SECONDS if deadline is None else deadline
        connection = sqlite3.connect(
            self._path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=0.05
        )
        connection.row_factory = sqlite3.Row
        try:
            if not write:
                connection.execute("PRAGMA query_only=ON")
            if deadline is not None:
                connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.OperationalError as exc:
            connection.set_progress_handler(None, 0)
            connection.rollback()
            if deadline is not None and "interrupted" in str(exc):
                raise CheckpointNotReady("projection-work repair I/O deadline exceeded") from exc
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _scope(self, scope: ProjectionScope) -> None:
        if scope.namespace != self._namespace or scope.projector_version != self._version:
            raise CheckpointConflict("projection-work scope is not owned by this store")
        if scope.anchor_event_id is None:
            raise CheckpointConflict("projection-work scope requires an executable anchor")

    def _enabled(self, connection: sqlite3.Connection) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM task_projection_work_projectors WHERE deployment_namespace=? "
                "AND projector_version=? AND enabled=1",
                (self._namespace, self._version),
            ).fetchone()
            is not None
        )

    def enable_projection_work(self) -> None:
        with self._connect(write=True) as connection:
            if self._enabled(connection):
                return
            count = connection.execute(
                "SELECT COUNT(*) FROM task_projection_work_projectors "
                "WHERE deployment_namespace=? AND enabled=1",
                (self._namespace,),
            ).fetchone()[0]
            if count >= MAX_ENABLED_PROJECTORS:
                raise ValueError("enabled projector version budget exhausted")
            connection.execute(
                "INSERT INTO task_projection_work_projectors "
                "(deployment_namespace,projector_version,enabled) VALUES (?,?,1) "
                "ON CONFLICT(deployment_namespace,projector_version) "
                "DO UPDATE SET enabled=1,bootstrap_after_task_id=NULL,bootstrap_complete=0",
                (self._namespace, self._version),
            )

    def disable_projection_work(self) -> None:
        with self._connect(write=True) as connection:
            connection.execute(
                "UPDATE task_projection_work_projectors SET enabled=0 "
                "WHERE deployment_namespace=? AND projector_version=?",
                (self._namespace, self._version),
            )

    def bootstrap_projection_work(self, *, limit: int = 32) -> bool:
        checked_limit(limit)
        key = (self._namespace, self._version)
        with self._connect(write=True) as connection:
            config = connection.execute(
                "SELECT * FROM task_projection_work_projectors "
                "WHERE deployment_namespace=? AND projector_version=?",
                key,
            ).fetchone()
            if config is None or not config["enabled"]:
                raise CheckpointNotReady("explicit projector enable required")
            if config["bootstrap_complete"]:
                return True
            cursor = config["bootstrap_after_task_id"]
            rows = connection.execute(
                "SELECT task_id,next_event_sequence FROM agent_tasks "
                "WHERE namespace=? AND task_id>? ORDER BY task_id LIMIT ?",
                (self._namespace, cursor or "", limit),
            ).fetchall()
            for row in rows:
                params = dict(
                    namespace=self._namespace,
                    task_id=row["task_id"],
                    version=self._version,
                    through=row["next_event_sequence"] - 1,
                )
                connection.execute(classified_pending(BOOTSTRAP_SOURCE), params)
                connection.execute(activate_privacy(BOOTSTRAP_SOURCE), params)
            done = len(rows) < limit
            connection.execute(
                "UPDATE task_projection_work_projectors SET bootstrap_after_task_id=?,"
                "bootstrap_complete=? WHERE deployment_namespace=? AND projector_version=?",
                (rows[-1]["task_id"] if rows else cursor, int(done), *key),
            )
            return done

    def read_pending_projection_work(
        self, *, limit: int = 32, after_scope: ProjectionScope | None = None
    ) -> tuple[ProjectionWork, ...]:
        checked_limit(limit)
        if after_scope is not None:
            self._scope(after_scope)
        cursor = ("", "") if after_scope is None else scope_values(after_scope)[1:3]
        with self._connect() as connection:
            if not self._enabled(connection):
                return ()
            return tuple(
                work_from_row(dict(row))
                for row in connection.execute(
                    PENDING, (self._namespace, self._version, *cursor, limit)
                ).fetchall()
            )

    def read_projection_work_repairs(
        self, *, limit: int = 32, after_task_id: TaskId | None = None
    ) -> tuple[ProjectionWorkRepair, ...]:
        checked_limit(limit)
        with self._connect() as connection:
            if not self._enabled(connection):
                return ()
            rows = connection.execute(
                "SELECT task_id,observed_through,wanted_through,needs_repair "
                "FROM task_projection_work_routes "
                "WHERE deployment_namespace=? AND projector_version=? AND needs_repair=1 "
                "AND task_id>? ORDER BY task_id LIMIT ?",
                (self._namespace, self._version, str(after_task_id or ""), limit),
            ).fetchall()
            return tuple(self._repair(row) for row in rows)

    def _repair(self, row: Mapping[str, Any] | sqlite3.Row) -> ProjectionWorkRepair:
        return ProjectionWorkRepair(
            ProjectionScope(self._namespace, TaskId(UUID(row["task_id"])), None, self._version),
            row["observed_through"],
            row["wanted_through"],
            bool(row["needs_repair"]),
        )

    def repair_projection_work(self, task_id: TaskId, *, limit: int = 256) -> ProjectionWorkRepair:
        checked_limit(limit, 256)
        deadline = time.monotonic() + PROJECTION_WORK_SECONDS
        with self._connect(write=True, deadline=deadline) as connection:
            task = connection.execute(
                "SELECT namespace,next_event_sequence,event_position_state,"
                f"{task_version('agent_tasks')} AS selected_version "
                "FROM agent_tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if task is None or task["namespace"] != self._namespace:
                raise CheckpointConflict("projection-work Task is outside namespace")
            if not self._enabled(connection):
                raise CheckpointNotReady("explicit projector enable required")
            key = (self._namespace, str(task_id), self._version)
            params = dict(
                namespace=self._namespace,
                task_id=str(task_id),
                version=self._version,
                through=task["next_event_sequence"] - 1,
            )
            connection.execute(classified_pending(BOOTSTRAP_SOURCE), params)
            connection.execute(activate_privacy(BOOTSTRAP_SOURCE), params)
            if self._version in (ORDINARY, COVERAGE) and task["selected_version"] != self._version:
                connection.execute(
                    "UPDATE task_projection_work_routes SET needs_repair=0 "
                    "WHERE deployment_namespace=? AND task_id=? AND projector_version=?",
                    key,
                )
                return self._repair(
                    dict(
                        task_id=str(task_id),
                        observed_through=-1,
                        wanted_through=-1,
                        needs_repair=0,
                    )
                )
            connection.commit()
            if task["event_position_state"] != "ready":
                raise CheckpointNotReady("explicit source position repair required")
            connection.execute("BEGIN IMMEDIATE")
            route = connection.execute(
                "SELECT * FROM task_projection_work_routes WHERE "
                "deployment_namespace=? AND task_id=? AND projector_version=?",
                key,
            ).fetchone()
            used = 0
            problem = None
            step_deadline = deadline - 0.2

            def parent_timer() -> int:
                return int(time.monotonic() >= deadline)

            def step_timer() -> int:
                return int(time.monotonic() >= step_deadline)

            for index in range(limit):
                if (
                    time.monotonic() >= step_deadline
                    or route["observed_through"] >= route["wanted_through"]
                ):
                    break
                connection.set_progress_handler(step_timer, 100)
                try:
                    if not connection.in_transaction:
                        connection.execute("BEGIN IMMEDIATE")
                        route = connection.execute(
                            "SELECT * FROM task_projection_work_routes WHERE "
                            "deployment_namespace=? AND task_id=? AND projector_version=?",
                            key,
                        ).fetchone()
                    if route["observed_through"] >= route["wanted_through"]:
                        break
                    size = connection.execute(
                        f"SELECT {HEADER_BYTES} AS header_bytes,replay_header_ready "
                        "FROM session_events INDEXED BY session_events_scalar_header "
                        "WHERE task_id=? AND task_sequence=?",
                        (str(task_id), route["observed_through"] + 1),
                    ).fetchone()
                    if size is None or not size["replay_header_ready"]:
                        problem = "explicit scalar header repair required"
                        break
                    if used + size["header_bytes"] > MAX_PROJECTION_WORK_BYTES:
                        if not index:
                            problem = "scalar header exceeds repair byte budget"
                        break
                    used += size["header_bytes"]
                    row = connection.execute(
                        "SELECT task_sequence,event_id,event_type,replay_command_kind,"
                        "replay_run_id,replay_internal_continuation,replay_header_ready "
                        "FROM session_events INDEXED BY session_events_scalar_header "
                        "WHERE task_id=? AND task_sequence=?",
                        (str(task_id), route["observed_through"] + 1),
                    ).fetchone()
                    if row is None or not row["replay_header_ready"]:
                        raise CheckpointNotReady("explicit scalar header repair required")
                    params = dict(
                        namespace=self._namespace,
                        task_id=str(task_id),
                        version=self._version,
                        event_id=row["event_id"],
                        task_sequence=row["task_sequence"],
                        event_type=row["event_type"],
                        command_kind=row["replay_command_kind"],
                        run_id=row["replay_run_id"],
                        internal=row["replay_internal_continuation"],
                    )
                    for statement in routed_statements(SOURCE):
                        connection.execute(statement, params)
                    completed = connection.execute(
                        "SELECT * FROM task_projection_work_routes WHERE "
                        "deployment_namespace=? AND task_id=? AND projector_version=?",
                        key,
                    ).fetchone()
                    # SQLITE_INTERRUPT rolls back the transaction; commit each complete header.
                    connection.set_progress_handler(parent_timer, 100)
                    connection.commit()
                    route = completed
                except sqlite3.OperationalError as exc:
                    if "interrupted" not in str(exc):
                        raise
                    connection.set_progress_handler(parent_timer, 100)
                    connection.rollback()
                    if not index:
                        problem = "projection-work repair I/O deadline exceeded"
                    break
                finally:
                    connection.set_progress_handler(parent_timer, 100)
            if problem is None:
                if not connection.in_transaction:
                    connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE task_projection_work_routes SET needs_repair="
                    "(observed_through<wanted_through) WHERE deployment_namespace=? "
                    "AND task_id=? AND projector_version=?",
                    key,
                )
                route = connection.execute(
                    "SELECT * FROM task_projection_work_routes WHERE "
                    "deployment_namespace=? AND task_id=? AND projector_version=?",
                    key,
                ).fetchone()
            result = self._repair(route)
        if problem is not None:
            raise CheckpointNotReady(problem)
        return result

    def _match(self, connection: sqlite3.Connection, work: ProjectionWork) -> bool:
        self._scope(work.scope)
        row = connection.execute(
            f"SELECT * FROM task_projection_work WHERE {WHERE}", scope_values(work.scope)
        ).fetchone()
        if row is None or (row["run_id"], row["anchor_sequence"]) != (
            work.run_id,
            work.anchor_sequence,
        ):
            raise CheckpointConflict("projection-work identity is not canonical")
        return bool(
            row["pending"]
            and row["problem_code"] is None
            and row["revision"] == work.revision
            and row["requested_through"] == work.requested_through
            and row["closed_through"] == work.closed_through
        )

    def complete_projection_work(self, work: ProjectionWork, *, expected_through: int) -> bool:
        if type(expected_through) is not int or expected_through != work.requested_through:
            raise CheckpointConflict("ACK must reach the exact requested frontier")
        with self._connect(write=True) as connection:
            if not self._match(connection, work):
                return False
            head = connection.execute(
                f"SELECT through_sequence FROM task_projection_heads WHERE {WHERE}",
                scope_values(work.scope),
            ).fetchone()
            if head is None or head[0] != expected_through:
                return False
            connection.execute(
                f"UPDATE task_projection_work SET pending=0 WHERE {WHERE}", scope_values(work.scope)
            )
            return True

    def defer_projection_work(
        self, work: ProjectionWork, *, problem_code: str, retry_after_seconds: float | None = None
    ) -> bool:
        delay = retry_delay(problem_code, retry_after_seconds)
        waiting = int(problem_code == "not_ready" and delay is None)
        with self._connect(write=True) as connection:
            if not self._match(connection, work):
                return False
            # ponytail: stop automatic retries after eight failures; operator repair can requeue.
            connection.execute(
                "UPDATE task_projection_work SET problem_code=?,dependency_wait=?,"
                "problem_attempts=problem_attempts+?,revision=revision+1,"
                f"retry_at=CASE WHEN ?=0 AND problem_attempts<7 THEN ? END WHERE {WHERE}",
                (
                    problem_code,
                    waiting,
                    1 - waiting,
                    waiting,
                    None if delay is None else time.time() + delay,
                    *scope_values(work.scope),
                ),
            )
            return True

    def read_projection_work_problem(self, scope: ProjectionScope) -> ProjectionWorkProblem | None:
        self._scope(scope)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT problem_code,problem_attempts,retry_at "
                f"FROM task_projection_work WHERE {WHERE}",
                scope_values(scope),
            ).fetchone()
            return (
                None
                if row is None or row[0] is None
                else ProjectionWorkProblem(scope, row[0], row[1], row[2])
            )

    def retry_projection_work(self, scope: ProjectionScope, *, expected_attempt: int) -> bool:
        self._scope(scope)
        if type(expected_attempt) is not int or not 0 <= expected_attempt <= 2_147_483_647:
            raise ValueError("invalid projection-work failure count")
        with self._connect(write=True) as connection:
            return (
                connection.execute(
                    "UPDATE task_projection_work SET problem_code=NULL,dependency_wait=0,"
                    f"retry_at=NULL,revision=revision+1 WHERE {WHERE} "
                    "AND problem_attempts=? AND problem_code IS NOT NULL AND pending=1",
                    (*scope_values(scope), expected_attempt),
                ).rowcount
                == 1
            )

    def retry_due_projection_work(self, *, limit: int = 32) -> int:
        checked_limit(limit)
        with self._connect(write=True) as connection:
            if not self._enabled(connection):
                return 0
            rows = connection.execute(
                "SELECT task_id,anchor_key FROM task_projection_work WHERE deployment_namespace=? "
                "AND projector_version=? AND pending=1 AND problem_code IS NOT NULL "
                "AND retry_at IS NOT NULL AND retry_at<=? "
                "ORDER BY retry_at,task_id,anchor_key LIMIT ?",
                (self._namespace, self._version, time.time(), limit),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE task_projection_work SET problem_code=NULL,dependency_wait=0,"
                    f"retry_at=NULL,revision=revision+1 WHERE {WHERE}",
                    (self._namespace, row[0], row[1], self._version),
                )
            return len(rows)
