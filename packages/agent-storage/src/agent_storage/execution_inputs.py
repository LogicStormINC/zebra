"""Native lease-fenced exact input frontier with bounded canonical admission."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from sqlite3 import OperationalError
from time import monotonic
from typing import Any
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEventPage
from agent_core.ports.execution_inputs import (
    INPUT_VERSION,
    MAX_INPUT_BYTES,
    ExecutionCompactionBoundary,
    ExecutionInputHead,
    ExecutionInputLimitExceeded,
    ExecutionInputState,
    execution_tool_output,
    fold_execution_inputs,
)
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
)

from agent_storage.postgres.task_io import current_task_io_deadline
from agent_storage.worker_progress import WorkerProgressStoreMixin

WHERE = "deployment_namespace=? AND task_id=? AND session_id=? AND input_version=?"


def execution_input_schema(*, postgres: bool = False) -> tuple[str, ...]:
    identity = "UUID" if postgres else "TEXT"
    return (
        f"""CREATE TABLE IF NOT EXISTS execution_input_heads (
        deployment_namespace TEXT NOT NULL, task_id {identity} NOT NULL,
        session_id {identity} NOT NULL, input_version TEXT NOT NULL,
        through_sequence BIGINT NOT NULL CHECK(through_sequence>=-1),
        last_event_id {identity},
        state_json TEXT NOT NULL,
        state_bytes INTEGER NOT NULL CHECK(state_bytes BETWEEN 1 AND 1048576),
        PRIMARY KEY(deployment_namespace,task_id,session_id,input_version),
        CHECK((through_sequence=-1)=(last_event_id IS NULL)))""",
    )


def execution_input_compaction_schema(*, postgres: bool = False) -> tuple[str, ...]:
    prefix = "deployment_namespace," if postgres else ""
    return (
        f"CREATE INDEX IF NOT EXISTS session_events_execution_evidence_boundary "
        f"ON session_events({prefix}task_id,session_id,event_type,"
        "replay_command_kind,task_sequence)",
    )


class ExecutionInputStore(WorkerProgressStoreMixin):
    """Explicit adapter: construction never migrates or repairs application data."""

    def __init__(
        self, database: Any, tasks: AgentTaskPort, *, namespace: str, postgres: bool = False
    ) -> None:
        if not namespace.strip() or len(namespace.encode()) > 256:
            raise ValueError("invalid execution input namespace")
        if postgres and namespace != database.deployment_namespace:
            raise ValueError("execution input namespace disagrees with database")
        self._database, self._tasks = database, tasks
        self._namespace, self._progress_postgres = namespace, postgres

    @property
    def namespace(self) -> str:
        return self._namespace

    @contextmanager
    def _progress_connection(self, *, write: bool = False) -> Iterator[Any]:
        if self._progress_postgres:
            with super()._progress_connection(write=write) as connection:
                yield connection
            return
        deadline = min(current_task_io_deadline() or monotonic() + 2, monotonic() + 2)
        with self._database.connect() as connection:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("execution input storage deadline exceeded")
            connection.execute(f"PRAGMA busy_timeout={max(1, int(remaining * 1000))}")
            connection.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                if monotonic() >= deadline:
                    raise TimeoutError("execution input storage deadline exceeded")
            except OperationalError as error:
                if monotonic() >= deadline:
                    raise TimeoutError("execution input storage deadline exceeded") from error
                raise
            finally:
                connection.set_progress_handler(None, 0)

    def _key(self, lease: WorkerLease, connection: Any = None) -> tuple[str, ...]:
        if self._progress_postgres and connection is not None:
            from agent_storage.postgres.agent_tasks import read_task_id_for_session

            # ponytail: resolve canonical membership once on this operation's
            # native socket/snapshot; never cache identity across operations.
            task = read_task_id_for_session(connection, self._namespace, lease.session_id)
        else:
            task = self._tasks.task_id_for_session(lease.session_id)
        if task is None:
            from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

            raise CheckpointNotReady("execution inputs require indexed Task membership")
        key = self._namespace, str(task), str(lease.session_id), INPUT_VERSION
        if not self._progress_postgres and connection is not None:
            self._membership(connection, key)
        return key

    def _membership(self, connection: Any, key: tuple[str, ...]) -> None:
        query = (
            "SELECT segment.task_id FROM execution_segments segment JOIN agent_tasks task "
            "ON task.task_id=segment.task_id WHERE task.namespace=? "
            "AND segment.session_id=? AND segment.task_id=?"
        )
        values = key[0], key[2], key[1]
        if self._progress_execute(connection, query, values).fetchone() is None:
            raise CheckpointConflict("execution input namespace/membership conflict")

    def _fence(self, connection: Any, lease: WorkerLease) -> None:
        if self._progress_postgres:
            from agent_storage.postgres.leases import assert_current_lease_fence

            assert_current_lease_fence(connection, self._namespace, lease.session_id, lease.fence)
            return
        row = connection.execute(
            "SELECT 1 FROM worker_leases lease JOIN control_plane_epochs epoch "
            "ON epoch.deployment_namespace='local' AND epoch.epoch=lease.control_plane_epoch "
            "WHERE lease.session_id=? AND lease.control_plane_epoch=? AND lease.fencing_token=? "
            "AND lease.worker_id=? AND lease.released_at IS NULL "
            "AND julianday(lease.expires_at)>julianday(?)",
            (
                str(lease.session_id),
                str(lease.fence.control_plane_epoch),
                lease.fence.fencing_token,
                lease.fence.owner_instance_id,
                datetime.now(UTC).isoformat(),
            ),
        ).fetchone()
        if row is None:
            raise LeaseLostError("execution input mutation rejected by current lease fence")

    def _head(self, connection: Any, key: tuple[str, ...]) -> ExecutionInputHead:
        byte_length = (
            "octet_length(state_json)"
            if self._progress_postgres
            else "length(CAST(state_json AS BLOB))"
        )
        # ponytail: the database gates body hydration by UTF-8 byte size; one
        # snapshot/query retains the 1-MiB trust boundary without a second fetch.
        row = self._progress_execute(
            connection,
            f"SELECT state_bytes,{byte_length} AS actual_bytes,through_sequence,last_event_id,"
            f"CASE WHEN state_bytes BETWEEN 1 AND {MAX_INPUT_BYTES} "
            f"AND {byte_length}=state_bytes THEN state_json END AS state_json "
            f"FROM execution_input_heads WHERE {WHERE}",
            key,
        ).fetchone()
        if row is None:
            return ExecutionInputHead(-1, ExecutionInputState())
        size = row["state_bytes"]
        if (
            type(size) is not int
            or not 0 < size <= MAX_INPUT_BYTES
            or row["actual_bytes"] != size
            or row["state_json"] is None
            or len(row["state_json"].encode()) != size
        ):
            raise CheckpointConflict("execution input state metadata exceeds bound")
        state = ExecutionInputState.model_validate_json(row["state_json"])
        state.encoded()
        if any(str(event.session_id) != key[2] for event in state.events):
            raise CheckpointConflict("execution input state crosses Session boundary")
        last = UUID(str(row["last_event_id"])) if row["last_event_id"] is not None else None
        head = ExecutionInputHead(row["through_sequence"], state, last)
        if last is not None:
            source_where = "deployment_namespace=? AND " if self._progress_postgres else ""
            values = (
                (key[0], key[1], head.through_sequence)
                if self._progress_postgres
                else (
                    key[1],
                    head.through_sequence,
                )
            )
            source = self._progress_execute(
                connection,
                f"SELECT event_id FROM session_events WHERE {source_where}"
                "task_id=? AND task_sequence=?",
                values,
            ).fetchone()
            if source is None or UUID(str(source["event_id"])) != last:
                raise CheckpointConflict("execution input frontier conflicts with canonical source")
        return head

    def read(self, lease: WorkerLease) -> ExecutionInputHead:
        with self._progress_connection() as connection:
            key = self._key(lease, connection)
            return self._head(connection, key)

    def _page(
        self, connection: Any, key: tuple[str, ...], after: int, through: int, limit: int = 256
    ) -> TaskEventPage:
        if self._progress_postgres:
            from agent_storage.postgres.task_event_pages import (
                read_task_event_page as postgres_page,
            )

            return postgres_page(
                connection,
                key[0],
                TaskId(UUID(key[1])),
                after,
                limit=limit,
                max_bytes=MAX_INPUT_BYTES,
                through=through,
            )
        from agent_storage.task_event_pages import read_task_event_page as sqlite_page

        return sqlite_page(
            connection,
            TaskId(UUID(key[1])),
            after,
            limit=limit,
            max_bytes=MAX_INPUT_BYTES,
            through=through,
        )

    def read_page(self, lease: WorkerLease, after: int, through: int) -> TaskEventPage:
        with self._progress_connection() as connection:
            key = self._key(lease, connection)
            try:
                return self._page(connection, key, after, through)
            except ValueError as error:
                message = str(error)
                if message in {
                    "Task Event positions require explicit backfill",
                    "Event byte bounds require explicit backfill",
                }:
                    raise CheckpointNotReady(message) from error
                if message.startswith("Task Event ") and "exceeds the page byte budget" in message:
                    raise ExecutionInputLimitExceeded(
                        "exact source event exceeds 1 MiB; execution preparation blocked"
                    ) from error
                raise

    def advance(self, lease: WorkerLease, page: TaskEventPage) -> ExecutionInputHead:
        with self._progress_connection(write=True) as connection:
            # Lease validation precedes derived head locks, and is repeated after
            # lock waits immediately before writing. No ownership callback substitutes it.
            if self._progress_postgres:
                from agent_storage.postgres.leases import lock_session_lease_boundary

                lock_session_lease_boundary(connection, self._namespace, lease.session_id)
            self._fence(connection, lease)
            key = self._key(lease, connection)
            canonical = self._page(
                connection, key, page.after_sequence, page.highwater, max(1, len(page.events))
            )
            if canonical != page:
                raise CheckpointConflict("execution input page conflicts with canonical source")
            empty = ExecutionInputState().encoded()
            self._progress_execute(
                connection,
                "INSERT INTO execution_input_heads VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (*key, -1, None, empty, len(empty.encode())),
            )
            if self._progress_postgres:
                self._progress_execute(
                    connection,
                    f"SELECT through_sequence FROM execution_input_heads WHERE {WHERE} FOR UPDATE",
                    key,
                )
            head = self._head(connection, key)
            if head.through_sequence != page.after_sequence:
                raise CheckpointStale("execution input frontier CAS changed")
            updated = fold_execution_inputs(
                head,
                canonical,
                lease,
                boundary=self._closed_boundary(connection, key, page.highwater),
                restored=self._referenced_exchanges(connection, key, head, canonical),
            )
            encoded = updated.state.encoded()
            self._fence(connection, lease)
            row = self._progress_execute(
                connection,
                f"UPDATE execution_input_heads SET through_sequence=?,last_event_id=?,state_json=?,"
                f"state_bytes=? WHERE {WHERE} AND through_sequence=? RETURNING through_sequence",
                (
                    updated.through_sequence,
                    str(updated.last_event_id) if updated.last_event_id is not None else None,
                    encoded,
                    len(encoded.encode()),
                    *key,
                    page.after_sequence,
                ),
            ).fetchone()
            if row is None:
                raise CheckpointStale("execution input frontier CAS changed")
            return updated

    def _referenced_exchanges(
        self, connection: Any, key: tuple[str, ...], head: ExecutionInputHead, page: TaskEventPage
    ) -> tuple[SessionEvent, ...]:
        evidence = head.state.evidence
        if evidence is None:
            return ()
        references = {
            item.event.payload.get("tool_call_id")
            for item in page.events
            if str(item.segment_id) == key[2]
            and item.event.event_type
            in {
                EventType.APPROVAL_REQUESTED,
                EventType.APPROVAL_GRANTED,
                EventType.APPROVAL_REJECTED,
                EventType.CLARIFICATION_REQUESTED,
                EventType.CLARIFICATION_RESPONDED,
            }
            and isinstance(item.event.payload.get("tool_call_id"), str)
        }
        restored: list[SessionEvent] = []
        used_bytes = 0
        for receipt in evidence.tools:
            if receipt.call_id not in references:
                continue
            offset = receipt.source_task_sequence - receipt.source_sequences[-1]
            exchange = []
            for sequence, identity in zip(
                receipt.source_sequences, receipt.source_event_ids, strict=True
            ):
                position = sequence + offset
                if position > head.through_sequence or position > page.highwater:
                    raise CheckpointConflict("archived exchange exceeds admitted source frontier")
                source = self._page(connection, key, position - 1, position, 1)
                if len(source.events) != 1:
                    raise CheckpointConflict("archived exchange source is unavailable")
                event = source.events[0].event
                if (
                    str(event.session_id) != key[2]
                    or event.event_id != identity
                    or event.sequence != sequence
                ):
                    raise CheckpointConflict("archived exchange source identity conflicts")
                used_bytes += len(event.model_dump_json().encode())
                if used_bytes > MAX_INPUT_BYTES:
                    raise ExecutionInputLimitExceeded("referenced exact exchanges exceed 1 MiB")
                exchange.append(event)
            execution_tool_output(receipt, exchange[-1])
            if (
                tuple(event.event_type for event in exchange)
                != (
                    EventType.TOOL_CALL_PROPOSED,
                    EventType.TOOL_EXECUTION_STARTED,
                    EventType.TOOL_EXECUTION_COMPLETED,
                )
                or any(event.payload.get("tool_call_id") != receipt.call_id for event in exchange)
                or any(event.payload.get("tool_name") != receipt.tool_name for event in exchange)
                or exchange[0].payload.get("arguments") != receipt.arguments
                or exchange[-1].payload.get("metadata") != receipt.metadata
                or exchange[-1].payload.get("status") != receipt.status
            ):
                raise CheckpointConflict("archived exchange evidence conflicts")
            restored.extend(exchange)
        return tuple(restored)

    def _closed_boundary(
        self,
        connection: Any,
        key: tuple[str, ...],
        highwater: int,
    ) -> ExecutionCompactionBoundary | None:
        # Seven covering-index seeks, not a scan of bodies or old Turns. Each
        # selected proof event is then admitted by the same 256/1-MiB page path.
        if self._progress_postgres:
            ready = connection.execute(
                "SELECT 1 FROM pg_class WHERE relname='session_events_execution_evidence_boundary' "
                "AND relkind='i' AND relnamespace=to_regnamespace(current_schema())"
            ).fetchone()
        else:
            ready = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='session_events_execution_evidence_boundary'"
            ).fetchone()
        if ready is None:
            raise CheckpointNotReady(
                "execution evidence boundary requires explicit index migration"
            )
        namespace = "deployment_namespace=? AND " if self._progress_postgres else ""
        base = (*key[:1], key[1], key[2]) if self._progress_postgres else (key[1], key[2])

        seek = (
            f"SELECT task_sequence FROM session_events WHERE {namespace}task_id=? "
            "AND session_id=? AND event_type=? AND replay_command_kind "
        )
        tail = "AND task_sequence<=? ORDER BY task_sequence DESC LIMIT 1"
        admission = self._progress_execute(
            connection, seek + "=? " + tail,
            (*base, "session_command_accepted", "run", highwater),
        ).fetchone()
        if admission is None:
            return None
        admission_sequence = admission["task_sequence"]
        terminal_kinds = (
            "turn_completed", "turn_failed", "turn_cancelled",
            "session_completed", "session_failed", "session_cancelled",
        )
        # UNION keeps six LIMIT-1 index seeks, while one round trip returns the
        # latest result. An IN/MAX scan could grow with a long execution history.
        terminals = " UNION ALL ".join(
            f"SELECT * FROM ({seek}IS NULL {tail}) terminal" for _ in terminal_kinds
        )
        result_sequence = self._progress_execute(
            connection, f"SELECT max(task_sequence) AS task_sequence FROM ({terminals}) results",
            tuple(
                value for kind in terminal_kinds for value in (*base, kind, admission_sequence - 1)
            ),
        ).fetchone()["task_sequence"]
        if result_sequence is None:
            return None
        result = self._page(connection, key, result_sequence - 1, result_sequence, 1).events[0]
        admission = self._page(
            connection, key, admission_sequence - 1, admission_sequence, 1
        ).events[0]
        if result.event.actor.value != "harness":
            return None
        payload = admission.event.payload.get("payload")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("run_id"), str)
            or (not payload["run_id"].strip())
        ):
            return None
        return ExecutionCompactionBoundary(result, admission)
