"""Native scoped progress checkpoints; no historical hydration on observation."""

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import UUID

from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId, TaskId
from agent_core.harness.progress_recovery import fold_progress_page
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
)
from agent_core.ports.task_replay import TaskRunHeader
from agent_core.ports.worker_progress import (
    MAX_PROGRESS_STATE_BYTES,
    PROGRESS_VERSION,
    WorkerProgressHead,
    WorkerProgressScope,
    WorkerProgressState,
    validate_progress_keys,
)

WHERE = "deployment_namespace=? AND task_id=? AND anchor_event_id=? AND projector_version=?"


def progress_schema(*, postgres: bool = False) -> tuple[str, ...]:
    identity = "UUID" if postgres else "TEXT"
    return (
        f"""CREATE TABLE IF NOT EXISTS worker_progress_heads (
            deployment_namespace TEXT NOT NULL, task_id {identity} NOT NULL,
            anchor_event_id {identity} NOT NULL, projector_version TEXT NOT NULL,
            run_id TEXT NOT NULL, anchor_sequence BIGINT NOT NULL CHECK(anchor_sequence>=0),
            through_sequence BIGINT NOT NULL, last_event_id {identity}, state_json TEXT NOT NULL,
            state_bytes INTEGER NOT NULL CHECK(state_bytes BETWEEN 1 AND 32768),
            PRIMARY KEY(deployment_namespace,task_id,anchor_event_id,projector_version),
            CHECK(through_sequence>=anchor_sequence-1),
            CHECK((through_sequence=anchor_sequence-1)=(last_event_id IS NULL)))""",
        f"""CREATE TABLE IF NOT EXISTS worker_progress_outputs (
            deployment_namespace TEXT NOT NULL, task_id {identity} NOT NULL,
            anchor_event_id {identity} NOT NULL, projector_version TEXT NOT NULL,
            output_id TEXT NOT NULL, task_sequence BIGINT NOT NULL CHECK(task_sequence>=0),
            signature TEXT NOT NULL CHECK(length(signature)=64),
            PRIMARY KEY(deployment_namespace,task_id,anchor_event_id,
                        projector_version,output_id))""",
        f"""CREATE TABLE IF NOT EXISTS worker_progress_receipts (
            deployment_namespace TEXT NOT NULL, task_id {identity} NOT NULL,
            anchor_event_id {identity} NOT NULL, projector_version TEXT NOT NULL,
            reference TEXT NOT NULL, task_sequence BIGINT NOT NULL CHECK(task_sequence>=0),
            PRIMARY KEY(deployment_namespace,task_id,anchor_event_id,
                        projector_version,reference))""",
    )


def _values(scope: WorkerProgressScope) -> tuple[str, ...]:
    return scope.namespace, str(scope.task_id), str(scope.anchor_event_id), scope.version


def _encoded(state: WorkerProgressState) -> tuple[str, int]:
    value = state.model_dump_json()
    size = len(value.encode("utf-8"))
    if size > MAX_PROGRESS_STATE_BYTES:
        raise ValueError("Worker progress state exceeds byte bound")
    return value, size


class WorkerProgressStoreMixin:
    _database: Any
    _progress_postgres = False

    def read_latest_run_header(self, task_id: TaskId) -> TaskRunHeader:
        with self._progress_connection() as connection:
            if self._progress_postgres:
                from agent_storage.postgres.task_replay_headers import (
                    read_latest_run_header as postgres_read_latest_run_header,
                )

                return postgres_read_latest_run_header(
                    connection, self._database.deployment_namespace, task_id
                )
            from agent_storage.task_replay_headers import (
                read_latest_run_header as sqlite_read_latest_run_header,
            )

            return sqlite_read_latest_run_header(connection, task_id)

    @contextmanager
    def _progress_connection(self, *, write: bool = False) -> Iterator[Any]:
        if self._progress_postgres:
            with self._database.connect_task_io() as connection:
                if not write:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                yield connection
        else:
            with self._database.connect() as connection:
                # ponytail: local SQLite retains its native single-writer ceiling;
                # cloud uses a scoped PostgreSQL head lock and cumulative I/O budget.
                deadline = monotonic() + 2
                connection.execute("PRAGMA busy_timeout=2000")
                connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                try:
                    yield connection
                finally:
                    connection.set_progress_handler(None, 0)

    def _progress_execute(self, connection: Any, statement: str, values: tuple[Any, ...]) -> Any:
        return connection.execute(
            statement.replace("?", "%s") if self._progress_postgres else statement, values
        )

    def _progress_run(self, connection: Any, scope: WorkerProgressScope) -> Any:
        if scope.version != PROGRESS_VERSION:
            raise CheckpointConflict("unsupported Worker progress version")
        if self._progress_postgres:
            from agent_storage.postgres.task_replay_headers import (
                read_run_header as postgres_read_run_header,
            )

            if scope.namespace != self._database.deployment_namespace:
                raise CheckpointConflict("Worker progress namespace mismatch")
            run = postgres_read_run_header(
                connection, scope.namespace, scope.task_id, scope.run_id, None
            )
        else:
            from agent_storage.task_replay_headers import read_run_header as sqlite_read_run_header

            row = connection.execute(
                "SELECT namespace FROM agent_tasks WHERE task_id=?", (str(scope.task_id),)
            ).fetchone()
            if row is None or row["namespace"] != scope.namespace:
                raise CheckpointConflict("Worker progress namespace mismatch")
            run = sqlite_read_run_header(connection, scope.task_id, scope.run_id, None)
        if (
            run.anchor is None
            or run.control_only
            or run.anchor.event_id != scope.anchor_event_id
            or run.start != scope.anchor_sequence
        ):
            raise CheckpointConflict("Worker progress anchor conflicts with canonical Run")
        return run

    def _progress_head(
        self, connection: Any, scope: WorkerProgressScope, *, initial: bool = False
    ) -> WorkerProgressHead:
        row = self._progress_execute(
            connection,
            f"SELECT run_id,anchor_sequence,state_bytes FROM worker_progress_heads WHERE {WHERE}",
            _values(scope),
        ).fetchone()
        if row is None:
            if initial:
                return WorkerProgressHead(
                    scope, scope.anchor_sequence - 1, None, WorkerProgressState()
                )
            raise CheckpointNotReady("Worker progress requires explicit preparation")
        if row["run_id"] != scope.run_id or row["anchor_sequence"] != scope.anchor_sequence:
            raise CheckpointConflict("Worker progress stored scope conflicts with Run")
        if not 0 < row["state_bytes"] <= MAX_PROGRESS_STATE_BYTES:
            raise CheckpointConflict("Worker progress stored state exceeds byte bound")
        state_row = self._progress_execute(
            connection,
            f"SELECT through_sequence,last_event_id,state_json FROM worker_progress_heads "
            f"WHERE {WHERE} AND state_bytes=?",
            (*_values(scope), row["state_bytes"]),
        ).fetchone()
        if state_row is None or len(state_row["state_json"].encode("utf-8")) != row["state_bytes"]:
            raise CheckpointConflict("Worker progress state metadata conflicts")
        last = state_row["last_event_id"]
        return WorkerProgressHead(
            scope,
            state_row["through_sequence"],
            EventId(UUID(str(last))) if last is not None else None,
            WorkerProgressState.model_validate_json(state_row["state_json"]),
        )

    def _progress_signature(self, connection: Any, scope: WorkerProgressScope, output: str) -> Any:
        row = self._progress_execute(
            connection,
            f"SELECT signature FROM worker_progress_outputs WHERE {WHERE} AND output_id=?",
            (*_values(scope), output),
        ).fetchone()
        return None if row is None else row["signature"]

    def read_worker_progress(self, scope: WorkerProgressScope) -> WorkerProgressHead:
        with self._progress_connection() as connection:
            run = self._progress_run(connection, scope)
            head = self._progress_head(connection, scope)
            if head.through_sequence > run.highwater or (
                run.stop is not None and head.through_sequence >= run.stop
            ):
                raise CheckpointConflict("Worker progress frontier exceeds its Run")
            return head

    def worker_output_published(self, scope: WorkerProgressScope, output_id: str) -> bool:
        validate_progress_keys((output_id,), limit=1)
        with self._progress_connection() as connection:
            self._progress_run(connection, scope)
            self._progress_head(connection, scope)
            return self._progress_signature(connection, scope, output_id) is not None

    def worker_receipts_covered(
        self, scope: WorkerProgressScope, references: tuple[str, ...]
    ) -> frozenset[str]:
        validate_progress_keys(references)
        with self._progress_connection() as connection:
            self._progress_run(connection, scope)
            self._progress_head(connection, scope)
            if not references:
                return frozenset()
            rows = self._progress_execute(
                connection,
                f"SELECT reference FROM worker_progress_receipts WHERE {WHERE} "
                f"AND reference IN ({','.join('?' for _ in references)})",
                (*_values(scope), *references),
            ).fetchall()
            return frozenset(row["reference"] for row in rows)

    def advance_worker_progress(
        self, scope: WorkerProgressScope, page: TaskEventPage
    ) -> WorkerProgressHead:
        with self._progress_connection(write=True) as connection:
            run = self._progress_run(connection, scope)
            if not page.events or (run.stop is not None and page.next_sequence >= run.stop):
                raise CheckpointConflict("Worker progress page crosses its Run boundary")
            canonical = self._progress_canonical(connection, scope, page)
            if canonical.events != page.events:
                raise CheckpointConflict("Worker progress page conflicts with canonical source")
            initial_json, initial_size = _encoded(WorkerProgressState())
            self._progress_execute(
                connection,
                "INSERT INTO worker_progress_heads VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    *_values(scope),
                    scope.run_id,
                    scope.anchor_sequence,
                    scope.anchor_sequence - 1,
                    None,
                    initial_json,
                    initial_size,
                ),
            )
            if self._progress_postgres:
                self._progress_execute(
                    connection,
                    f"SELECT through_sequence FROM worker_progress_heads WHERE {WHERE} FOR UPDATE",
                    _values(scope),
                )
            head = self._progress_head(connection, scope)
            if head.through_sequence > page.after_sequence:
                raise CheckpointStale("Worker progress frontier CAS advanced")
            signatures: dict[str, str] = {}
            for entry in canonical.events:
                if entry.event.event_type is EventType.PUBLIC_OUTPUT:
                    output = PublicOutputPayload.model_validate(entry.event.payload)
                    signature = sha256(output.model_dump_json().encode("utf-8")).hexdigest()
                    previous = signatures.get(output.output_id) or self._progress_signature(
                        connection, scope, output.output_id
                    )
                    if previous is not None and previous != signature:
                        raise CheckpointConflict("Worker progress output identity changed")
                    signatures[output.output_id] = signature
            folded = fold_progress_page(
                head,
                canonical,
                output_published=lambda key: self._progress_signature(connection, scope, key)
                is not None,
            )
            encoded, size = _encoded(folded.head.state)
            for key, position in folded.outputs:
                self._progress_execute(
                    connection,
                    "INSERT INTO worker_progress_outputs VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (*_values(scope), key, position, signatures[key]),
                )
            for key, position in folded.receipts:
                self._progress_execute(
                    connection,
                    "INSERT INTO worker_progress_receipts VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (*_values(scope), key, position),
                )
            cursor = self._progress_execute(
                connection,
                f"UPDATE worker_progress_heads SET through_sequence=?,last_event_id=?,state_json=?,"
                f"state_bytes=? WHERE {WHERE} AND through_sequence=?",
                (
                    folded.head.through_sequence,
                    str(folded.head.last_event_id),
                    encoded,
                    size,
                    *_values(scope),
                    page.after_sequence,
                ),
            )
            if cursor.rowcount != 1:
                raise CheckpointConflict("Worker progress frontier CAS failed")
            return folded.head

    def _progress_canonical(
        self, connection: Any, scope: WorkerProgressScope, page: TaskEventPage
    ) -> TaskEventPage:
        if self._progress_postgres:
            from agent_storage.postgres.task_event_pages import (
                read_task_event_page as postgres_read_task_event_page,
            )

            return postgres_read_task_event_page(
                connection,
                scope.namespace,
                scope.task_id,
                page.after_sequence,
                limit=len(page.events),
                max_bytes=1_048_576,
                through=page.next_sequence,
            )
        from agent_storage.task_event_pages import (
            read_task_event_page as sqlite_read_task_event_page,
        )

        return sqlite_read_task_event_page(
            connection,
            scope.task_id,
            page.after_sequence,
            limit=len(page.events),
            max_bytes=1_048_576,
            through=page.next_sequence,
        )
