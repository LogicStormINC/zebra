"""PostgreSQL scalar derived-work queue, independent of Task execution."""

import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, cast
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionScope,
)
from agent_core.ports.task_projection_work import (
    MAX_ENABLED_PROJECTORS,
    MAX_PROJECTION_WORK_BYTES,
    PROJECTION_WORK_SECONDS,
    ProjectionWork,
    ProjectionWorkProblem,
    ProjectionWorkRepair,
    TaskProjectionWorkPort,
)
from psycopg import ClientCursor, Connection, Cursor
from psycopg.errors import QueryCanceled

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_io import TaskIoConnection
from agent_storage.projection_work import (
    PENDING,
    WHERE,
    checked_limit,
    retry_delay,
    scope_values,
    work_from_row,
)
from agent_storage.projection_work_routing import (
    COVERAGE,
    ORDINARY,
    PG_BOOTSTRAP_SOURCE,
    activate_privacy,
    classified_pending,
    routed_statements,
    task_version,
)

PG_WHERE = WHERE.replace("?", "%s")
PG_PENDING = PENDING.replace("?", "%s").replace("h.task_id=w.task_id", "h.task_id=w.task_id::uuid")
SOURCE = """SELECT %(namespace)s::text AS deployment_namespace,%(task_id)s::text AS task_id,
 %(event_id)s::text AS event_id,%(task_sequence)s::bigint AS task_sequence,
 %(event_type)s::text AS event_type,%(command_kind)s::text AS command_kind,
 %(run_id)s::text AS run_id,%(internal)s::integer AS internal,
 %(version)s::text AS selected_version"""
HEADER_BYTES = "128+" + "+".join(
    f"COALESCE(octet_length({name}::text),0)"
    for name in ("event_id", "event_type", "replay_command_kind", "replay_run_id")
)


class _WorkConnection:
    """Remaining SQL operation budget, shared by all statements and COMMIT."""

    def __init__(self, connection: Connection[dict[str, Any]], deadline: float) -> None:
        self.connection, self.deadline = connection, deadline

    def execute(
        self, statement: str, params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Cursor[dict[str, Any]]:
        remaining = int((self.deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            raise CheckpointNotReady("projection-work operation I/O deadline exceeded")
        try:
            self.connection.execute(
                "SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                (f"{remaining}ms", f"{min(50, remaining)}ms"),
            )
            return self.connection.execute(statement, params)
        except (QueryCanceled, TimeoutError) as exc:
            raise CheckpointNotReady("projection-work operation I/O deadline exceeded") from exc

    def commit(self) -> None:
        self.execute("COMMIT")


class PostgresTaskProjectionWorkStore(TaskProjectionWorkPort):
    def __init__(self, database: PostgresDatabase, projector_version: str) -> None:
        ProjectionScope(database.deployment_namespace, TaskId(UUID(int=0)), None, projector_version)
        self._database = database
        self._namespace = database.deployment_namespace
        self._version = projector_version

    @contextmanager
    def _connect(
        self, *, write: bool = False, deadline: float | None = None
    ) -> Iterator[_WorkConnection]:
        deadline = time.monotonic() + PROJECTION_WORK_SECONDS if deadline is None else deadline
        try:
            with self._database.connect_task_io(
                deadline=deadline, client_cursor=True
            ) as connection:
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL "
                    + ("READ COMMITTED" if write else "REPEATABLE READ READ ONLY")
                )
                # Ordered scalar seeks must not become whole-candidate bitmap/sort scans.
                connection.execute("SET LOCAL enable_bitmapscan=off")
                connection.execute("SET LOCAL enable_seqscan=off")
                # Native I/O reserves cleanup time too; SQL must finish before that boundary.
                bounded = _WorkConnection(
                    connection, cast(TaskIoConnection, connection).operation_deadline
                )
                yield bounded
                bounded.commit()
        except TimeoutError as exc:
            raise CheckpointNotReady("projection-work operation I/O deadline exceeded") from exc

    def _scope(self, scope: ProjectionScope) -> None:
        if scope.namespace != self._namespace or scope.projector_version != self._version:
            raise CheckpointConflict("projection-work scope is not owned by this store")
        if scope.anchor_event_id is None:
            raise CheckpointConflict("projection-work scope requires an executable anchor")

    def _enabled(self, connection: _WorkConnection) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM task_projection_work_projectors WHERE deployment_namespace=%s "
                "AND projector_version=%s AND enabled=1",
                (self._namespace, self._version),
            ).fetchone()
            is not None
        )

    def enable_projection_work(self) -> None:
        with self._connect(write=True) as connection:
            # Same namespace serializes only configuration, never provider/tool I/O.
            connection.execute("SELECT pg_advisory_xact_lock(68,hashtext(%s))", (self._namespace,))
            if self._enabled(connection):
                return
            count_row = connection.execute(
                "SELECT COUNT(*) AS n FROM task_projection_work_projectors "
                "WHERE deployment_namespace=%s AND enabled=1",
                (self._namespace,),
            ).fetchone()
            assert count_row is not None
            if count_row["n"] >= MAX_ENABLED_PROJECTORS:
                raise ValueError("enabled projector version budget exhausted")
            connection.execute(
                "INSERT INTO task_projection_work_projectors "
                "(deployment_namespace,projector_version,enabled) VALUES (%s,%s,1) "
                "ON CONFLICT(deployment_namespace,projector_version) DO UPDATE SET enabled=1,"
                "bootstrap_after_task_id=NULL,bootstrap_complete=0",
                (self._namespace, self._version),
            )

    def disable_projection_work(self) -> None:
        with self._connect(write=True) as connection:
            connection.execute(
                "UPDATE task_projection_work_projectors SET enabled=0 "
                "WHERE deployment_namespace=%s "
                "AND projector_version=%s",
                (self._namespace, self._version),
            )

    def bootstrap_projection_work(self, *, limit: int = 32) -> bool:
        checked_limit(limit)
        key = (self._namespace, self._version)
        with self._connect(write=True) as connection:
            config = connection.execute(
                "SELECT * FROM task_projection_work_projectors "
                "WHERE deployment_namespace=%s AND projector_version=%s "
                "FOR UPDATE",
                key,
            ).fetchone()
            if config is None or not config["enabled"]:
                raise CheckpointNotReady("explicit projector enable required")
            if config["bootstrap_complete"]:
                return True
            cursor = config["bootstrap_after_task_id"]
            suffix, params = (
                ("", (*key[:1], limit))
                if cursor is None
                else (" AND task_id>%s", (self._namespace, UUID(cursor), limit))
            )
            rows = connection.execute(
                "SELECT task_id,next_event_sequence FROM agent_tasks "
                "WHERE deployment_namespace=%s" + suffix + " ORDER BY task_id LIMIT %s FOR SHARE",
                params,
            ).fetchall()
            # Native assignment updates this Task HWM before routing. Share locks either
            # observe its commit or leave the discovery cursor unchanged on bounded retry.
            for row in rows:
                enqueue_params = dict(
                    namespace=self._namespace,
                    task_id=str(row["task_id"]),
                    version=self._version,
                    through=row["next_event_sequence"] - 1,
                )
                connection.execute(
                    classified_pending(PG_BOOTSTRAP_SOURCE, postgres=True), enqueue_params
                )
                connection.execute(
                    activate_privacy(PG_BOOTSTRAP_SOURCE, postgres=True), enqueue_params
                )
            done = len(rows) < limit
            connection.execute(
                "UPDATE task_projection_work_projectors SET bootstrap_after_task_id=%s,"
                "bootstrap_complete=%s WHERE deployment_namespace=%s AND projector_version=%s",
                (str(rows[-1]["task_id"]) if rows else cursor, int(done), *key),
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
                work_from_row(row)
                for row in connection.execute(
                    PG_PENDING, (self._namespace, self._version, *cursor, limit)
                ).fetchall()
            )

    def _repair(self, row: dict[str, Any]) -> ProjectionWorkRepair:
        return ProjectionWorkRepair(
            ProjectionScope(self._namespace, TaskId(UUID(row["task_id"])), None, self._version),
            row["observed_through"],
            row["wanted_through"],
            bool(row["needs_repair"]),
        )

    def read_projection_work_repairs(
        self, *, limit: int = 32, after_task_id: TaskId | None = None
    ) -> tuple[ProjectionWorkRepair, ...]:
        checked_limit(limit)
        with self._connect() as connection:
            if not self._enabled(connection):
                return ()
            return tuple(
                self._repair(row)
                for row in connection.execute(
                    "SELECT task_id,observed_through,wanted_through,needs_repair "
                    "FROM task_projection_work_routes "
                    "WHERE deployment_namespace=%s AND projector_version=%s AND needs_repair=1 "
                    "AND task_id>%s ORDER BY task_id LIMIT %s",
                    (self._namespace, self._version, str(after_task_id or ""), limit),
                ).fetchall()
            )

    def repair_projection_work(self, task_id: TaskId, *, limit: int = 256) -> ProjectionWorkRepair:
        checked_limit(limit, 256)
        deadline = time.monotonic() + PROJECTION_WORK_SECONDS
        key = (self._namespace, str(task_id), self._version)
        with self._connect(write=True, deadline=deadline) as connection:
            execute = connection.execute
            task = execute(
                "SELECT next_event_sequence,event_position_state,"
                f"{task_version('agent_tasks', postgres=True)} AS selected_version "
                "FROM agent_tasks "
                "WHERE deployment_namespace=%s AND task_id=%s",
                (self._namespace, task_id),
            ).fetchone()
            if task is None:
                raise CheckpointConflict("projection-work Task is outside namespace")
            if not self._enabled(connection):
                raise CheckpointNotReady("explicit projector enable required")
            params = dict(
                namespace=self._namespace,
                task_id=str(task_id),
                version=self._version,
                through=task["next_event_sequence"] - 1,
            )
            execute(classified_pending(PG_BOOTSTRAP_SOURCE, postgres=True), params)
            execute(activate_privacy(PG_BOOTSTRAP_SOURCE, postgres=True), params)
            if self._version in (ORDINARY, COVERAGE) and task["selected_version"] != self._version:
                execute(
                    "UPDATE task_projection_work_routes SET needs_repair=0 "
                    "WHERE deployment_namespace=%s AND task_id=%s AND projector_version=%s",
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
            # Discovery survives page cancellation; no source-row locks are taken by repair.
            connection.commit()
            if task["event_position_state"] != "ready":
                raise CheckpointNotReady("explicit source position repair required")
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            route = execute(
                "SELECT * FROM task_projection_work_routes WHERE deployment_namespace=%s "
                "AND task_id=%s AND projector_version=%s FOR UPDATE",
                key,
            ).fetchone()
            assert route is not None
            used = 0
            problem = None
            # ponytail: bound header repair to 100ms to reduce canonical COMMIT contention.
            # Each header is atomic; the committed prefix resumes on the next tick.
            deadline = min(connection.deadline - 0.2, time.monotonic() + 0.1)
            step = _WorkConnection(connection.connection, deadline)
            routing = "BEGIN " + ";".join(routed_statements(SOURCE, postgres=True)) + ";END"
            for index in range(limit):
                remaining = step.deadline - time.monotonic()
                if remaining <= 0 or route["observed_through"] >= route["wanted_through"]:
                    break
                connection.execute("SAVEPOINT projection_work_header")
                try:
                    size = step.execute(
                        f"SELECT {HEADER_BYTES} AS header_bytes,replay_header_ready "
                        "FROM session_events "
                        "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s",
                        (self._namespace, task_id, route["observed_through"] + 1),
                    ).fetchone()
                    if size is None or not size["replay_header_ready"]:
                        problem = "explicit scalar header repair required"
                        break
                    if used + size["header_bytes"] > MAX_PROJECTION_WORK_BYTES:
                        if not index:
                            problem = "scalar header exceeds repair byte budget"
                        break
                    used += size["header_bytes"]
                    row = step.execute(
                        "SELECT task_sequence,event_id,event_type,replay_command_kind,"
                        "replay_run_id,replay_internal_continuation,replay_header_ready "
                        "FROM session_events "
                        "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s",
                        (self._namespace, task_id, route["observed_through"] + 1),
                    ).fetchone()
                    if row is None or not row["replay_header_ready"]:
                        raise CheckpointNotReady("explicit scalar header repair required")
                    params = dict(
                        namespace=self._namespace,
                        task_id=str(task_id),
                        version=self._version,
                        event_id=str(row["event_id"]),
                        task_sequence=row["task_sequence"],
                        event_type=row["event_type"],
                        command_kind=row["replay_command_kind"],
                        run_id=row["replay_run_id"],
                        internal=int(row["replay_internal_continuation"]),
                    )
                    code = ClientCursor(connection.connection).mogrify(routing, params)
                    # Quote both levels; one DO statement shares the whole header's SQL deadline.
                    step.execute("DO %s", (code,))
                    completed = step.execute(
                        "SELECT * FROM task_projection_work_routes WHERE deployment_namespace=%s "
                        "AND task_id=%s AND projector_version=%s",
                        key,
                    ).fetchone()
                    assert completed is not None
                    route = completed
                except CheckpointNotReady as exc:
                    if connection.connection.closed:
                        raise  # Transport expiry is not a recoverable savepoint cancellation.
                    # set_config cannot run in an aborted transaction; recover natively first.
                    connection.connection.execute("ROLLBACK TO SAVEPOINT projection_work_header")
                    if not index:
                        problem = str(exc)
                    break
                finally:
                    if not connection.connection.closed:
                        connection.execute("RELEASE SAVEPOINT projection_work_header")
            if problem is None:
                route = execute(
                    "UPDATE task_projection_work_routes SET needs_repair="
                    "CAST(observed_through<wanted_through AS INTEGER) "
                    "WHERE deployment_namespace=%s AND task_id=%s AND projector_version=%s "
                    "RETURNING *",
                    key,
                ).fetchone()
                assert route is not None
            result = self._repair(route)
        if problem is not None:
            raise CheckpointNotReady(problem)
        return result

    def _match(self, connection: _WorkConnection, work: ProjectionWork) -> bool:
        self._scope(work.scope)
        row = connection.execute(
            f"SELECT * FROM task_projection_work WHERE {PG_WHERE} FOR UPDATE",
            scope_values(work.scope),
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
                f"SELECT through_sequence FROM task_projection_heads WHERE {PG_WHERE}",
                scope_values(work.scope),
            ).fetchone()
            if head is None or head["through_sequence"] != expected_through:
                return False
            connection.execute(
                f"UPDATE task_projection_work SET pending=0 WHERE {PG_WHERE}",
                scope_values(work.scope),
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
            connection.execute(
                "UPDATE task_projection_work SET problem_code=%s,dependency_wait=%s,"
                "problem_attempts=problem_attempts+%s,revision=revision+1,"
                f"retry_at=CASE WHEN %s=0 AND problem_attempts<7 THEN %s::double precision END "
                f"WHERE {PG_WHERE}",
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
                f"FROM task_projection_work WHERE {PG_WHERE}",
                scope_values(scope),
            ).fetchone()
            return (
                None
                if row is None or row["problem_code"] is None
                else ProjectionWorkProblem(
                    scope, row["problem_code"], row["problem_attempts"], row["retry_at"]
                )
            )

    def retry_projection_work(self, scope: ProjectionScope, *, expected_attempt: int) -> bool:
        self._scope(scope)
        if type(expected_attempt) is not int or not 0 <= expected_attempt <= 2_147_483_647:
            raise ValueError("invalid projection-work failure count")
        with self._connect(write=True) as connection:
            return (
                connection.execute(
                    "UPDATE task_projection_work SET problem_code=NULL,dependency_wait=0,"
                    "retry_at=NULL,"
                    f"revision=revision+1 WHERE {PG_WHERE} "
                    "AND problem_attempts=%s AND problem_code IS NOT NULL AND pending=1",
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
                "SELECT task_id,anchor_key FROM task_projection_work "
                "WHERE deployment_namespace=%s AND projector_version=%s AND pending=1 "
                "AND problem_code IS NOT NULL AND retry_at IS NOT NULL "
                "AND retry_at<=%s ORDER BY retry_at,task_id,anchor_key "
                "LIMIT %s FOR UPDATE SKIP LOCKED",
                (self._namespace, self._version, time.time(), limit),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE task_projection_work SET problem_code=NULL,dependency_wait=0,"
                    f"retry_at=NULL,revision=revision+1 WHERE {PG_WHERE}",
                    (self._namespace, row["task_id"], row["anchor_key"], self._version),
                )
            return len(rows)
