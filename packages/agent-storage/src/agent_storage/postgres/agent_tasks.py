"""Namespace-scoped PostgreSQL Task and Segment Store facade."""

from agent_core.domain.agent_tasks import AgentTask, ExecutionSegment, RolloverReason
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.agent_tasks import FencedAgentTaskStorePort, TaskEvent, TaskEventPage
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_core.ports.task_replay import TaskEventHeader, TaskReadHeader, TaskRunHeader

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projection_source_metadata import (
    PostgresProjectionSourceMetadataMixin,
    backfill_projection_source_metadata,
)
from agent_storage.postgres.task_event_pages import read_task_event_page
from agent_storage.postgres.task_event_positions import backfill_task_event_positions
from agent_storage.postgres.task_index_transactions import (
    _require_task,
    attach_segment_for_worker_in_transaction,
    attach_segment_in_transaction,
    get_task_in_transaction,
    rebuild_task_in_transaction,
)
from agent_storage.postgres.task_io import TaskIoConnections
from agent_storage.postgres.task_lineage import (
    EVENT_COLUMNS,
    PostgresAgentTaskConflictError,
    root_for_session,
    segment_from_row,
    task_event_from_row,
)
from agent_storage.postgres.task_projection_checkpoints import PostgresTaskProjectionCheckpointMixin
from agent_storage.postgres.task_read_summaries import PostgresTaskReadSummaryMixin
from agent_storage.postgres.task_replay_headers import (
    backfill_task_replay_headers,
    read_event_header,
    read_run_header,
)
from agent_storage.postgres.worker_progress import PostgresWorkerProgressMixin


class PostgresAgentTaskStore(
    PostgresTaskReadSummaryMixin,
    PostgresWorkerProgressMixin,
    PostgresProjectionSourceMetadataMixin,
    PostgresTaskProjectionCheckpointMixin,
    FencedAgentTaskStorePort,
):
    """Explicitly rebuilt Task index whose read methods never write."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        task_io_connections: TaskIoConnections | None = None,
    ) -> None:
        self._database = PostgresDatabase(
            dsn, deployment_namespace=deployment_namespace, task_io_connections=task_io_connections
        )

    def ensure_for_session(self, session_id: SessionId) -> AgentTask:
        with self._database.connect() as connection:
            root_id = root_for_session(
                connection,
                self._database.deployment_namespace,
                session_id,
            )
            return rebuild_task_in_transaction(
                connection,
                self._database.deployment_namespace,
                root_id,
            )

    def rebuild_all(self) -> int:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT COALESCE(
                    received.payload ->> 'root_session_id',
                    projection.session_id::text
                )::uuid AS root_session_id
                FROM session_projections projection
                LEFT JOIN session_events received
                  ON received.deployment_namespace = projection.deployment_namespace
                 AND received.session_id = projection.session_id
                 AND received.event_type = %s
                WHERE projection.deployment_namespace = %s
                ORDER BY root_session_id
                """,
                (
                    EventType.SESSION_HANDOFF_RECEIVED.value,
                    self._database.deployment_namespace,
                ),
            ).fetchall()
            for row in rows:
                rebuild_task_in_transaction(
                    connection,
                    self._database.deployment_namespace,
                    SessionId(row["root_session_id"]),
                )
            return len(rows)

    def get_task(self, task_id: TaskId) -> AgentTask | None:
        with self._database.connect_task_io() as connection:
            return get_task_in_transaction(
                connection,
                self._database.deployment_namespace,
                task_id,
            )

    def list_tasks(self, *, limit: int) -> tuple[AgentTask, ...]:
        if limit <= 0:
            return ()
        with self._database.connect_task_io() as connection:
            rows = connection.execute(
                """
                SELECT task_id FROM agent_tasks
                WHERE deployment_namespace = %s
                ORDER BY updated_at DESC, task_id
                LIMIT %s
                """,
                (self._database.deployment_namespace, limit),
            ).fetchall()
            return tuple(
                _require_task(
                    connection,
                    self._database.deployment_namespace,
                    TaskId(row["task_id"]),
                )
                for row in rows
            )

    def read_task_header(self, task_id: TaskId) -> TaskReadHeader | None:
        with self._database.connect_task_io() as connection:
            row = connection.execute(
                "SELECT t.active_segment_id,t.next_event_sequence,t.event_position_state,"
                "h.title,h.status,h.current_sequence AS active_segment_sequence,"
                "h.title_truncated,h.clarification_id,h.clarification_invalid "
                "FROM agent_tasks t LEFT JOIN session_observation_headers h "
                "ON h.deployment_namespace=t.deployment_namespace "
                "AND h.session_id=t.active_segment_id::text "
                "WHERE t.deployment_namespace=%s AND t.task_id=%s",
                (self._database.deployment_namespace, task_id),
            ).fetchone()
        if row is None:
            return None
        if row["event_position_state"] != "ready":
            raise CheckpointNotReady("Task Event positions require explicit backfill")
        return TaskReadHeader(
            task_id,
            SessionId(row["active_segment_id"]),
            row["next_event_sequence"] - 1,
            title=row["title"],
            status=SessionStatus(row["status"]) if row["status"] is not None else None,
            active_segment_sequence=row["active_segment_sequence"],
            title_truncated=bool(row["title_truncated"]),
            clarification_id=row["clarification_id"],
            clarification_invalid=bool(row["clarification_invalid"]),
        )

    def segments(self, task_id: TaskId) -> tuple[ExecutionSegment, ...]:
        with self._database.connect_task_io() as connection:
            rows = connection.execute(
                """
                SELECT session_id, task_id, predecessor_id, segment_index,
                       visibility, rollover_reason
                FROM execution_segments
                WHERE deployment_namespace = %s AND task_id = %s
                ORDER BY segment_index
                """,
                (self._database.deployment_namespace, task_id),
            ).fetchall()
        return tuple(segment_from_row(row) for row in rows)

    def active_segment(self, task_id: TaskId) -> SessionId | None:
        task = self.get_task(task_id)
        return None if task is None else task.active_segment_id

    def task_id_for_session(self, session_id: SessionId) -> TaskId | None:
        with self._database.connect_task_io() as connection:
            row = connection.execute(
                """
                SELECT task_id FROM execution_segments
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchone()
        return None if row is None else TaskId(row["task_id"])

    def is_internal_segment(self, session_id: SessionId) -> bool:
        task_id = self.task_id_for_session(session_id)
        return task_id is not None and task_id != session_id

    def attach_segment(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        *,
        predecessor_id: SessionId,
        reason: RolloverReason,
    ) -> AgentTask:
        raise PostgresAgentTaskConflictError(
            "direct PostgreSQL Task rollover requires WorkerMutationAuthority"
        )

    def attach_segment_for_worker(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        *,
        predecessor_id: SessionId,
        reason: RolloverReason,
        authority: WorkerMutationAuthority,
    ) -> AgentTask:
        with self._database.connect() as connection:
            attach_segment_for_worker_in_transaction(
                connection,
                self._database.deployment_namespace,
                task_id=task_id,
                segment_id=segment_id,
                predecessor_id=predecessor_id,
                reason=reason,
                authority=authority,
            )
            return _require_task(connection, self._database.deployment_namespace, task_id)

    def read_events(self, task_id: TaskId, after_sequence: int) -> tuple[TaskEvent, ...]:
        if after_sequence < -1:
            raise ValueError("task event cursor must be greater than or equal to -1")
        with self._database.connect() as connection:
            state = connection.execute(
                """SELECT event_position_state FROM agent_tasks
                   WHERE deployment_namespace=%s AND task_id=%s""",
                (self._database.deployment_namespace, task_id),
            ).fetchone()
            if state is not None and state["event_position_state"] != "ready":
                raise PostgresAgentTaskConflictError(
                    "Task Event positions require explicit backfill"
                )
            rows = connection.execute(
                f"""
                SELECT event.task_sequence, event.session_id AS segment_id,
                       event.sequence AS segment_sequence, {EVENT_COLUMNS}
                FROM session_events event
                WHERE event.deployment_namespace = %s
                  AND event.task_id = %s AND event.task_sequence > %s
                ORDER BY event.task_sequence
                """,
                (self._database.deployment_namespace, task_id, after_sequence),
            ).fetchall()
        return tuple(task_event_from_row(task_id, row) for row in rows)

    def backfill_event_positions(self, task_id: TaskId, *, limit: int = 256) -> bool:
        """Operator-owned bounded transaction; callers repeat only while not ready."""
        with self._database.connect_task_io() as connection:
            return backfill_task_event_positions(
                connection, self._database.deployment_namespace, task_id, limit=limit
            )

    def read_event_page(
        self,
        task_id: TaskId,
        after_sequence: int,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        through_sequence: int | None = None,
    ) -> TaskEventPage:
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return read_task_event_page(
                connection,
                self._database.deployment_namespace,
                task_id,
                after_sequence,
                limit=limit,
                max_bytes=max_bytes,
                through=through_sequence,
            )

    def backfill_replay_headers(
        self,
        task_id: TaskId,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        timeout_seconds: float = 2.0,
    ) -> bool:
        """Explicit write-owned maintenance; observation never invokes it."""
        with self._database.connect_task_io(timeout_seconds=timeout_seconds) as connection:
            return backfill_task_replay_headers(
                connection,
                self._database.deployment_namespace,
                task_id,
                limit=limit,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )

    def read_event_header(self, task_id: TaskId, task_sequence: int) -> TaskEventHeader | None:
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return read_event_header(
                connection,
                self._database.deployment_namespace,
                task_id,
                task_sequence,
            )

    def backfill_projection_sources(self, task_id: TaskId, *, limit: int = 256) -> bool:
        """Explicit metadata maintenance, not a side effect of observation."""
        with self._database.connect_task_io() as connection:
            return backfill_projection_source_metadata(
                connection,
                self._database.deployment_namespace,
                task_id,
                limit=limit,
            )

    def read_run_header(
        self,
        task_id: TaskId,
        run_id: str,
        *,
        through_sequence: int | None = None,
    ) -> TaskRunHeader:
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return read_run_header(
                connection, self._database.deployment_namespace, task_id, run_id, through_sequence
            )


__all__ = [
    "FencedAgentTaskStorePort",
    "PostgresAgentTaskConflictError",
    "PostgresAgentTaskStore",
    "attach_segment_in_transaction",
    "attach_segment_for_worker_in_transaction",
    "rebuild_task_in_transaction",
]
