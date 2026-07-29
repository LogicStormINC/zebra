"""Namespace-scoped PostgreSQL Task and Segment Store facade."""

from agent_core.domain.agent_tasks import AgentTask, ExecutionSegment, RolloverReason
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_index_transactions import (
    _require_task,
    attach_segment_in_transaction,
    get_task_in_transaction,
    rebuild_task_in_transaction,
)
from agent_storage.postgres.task_lineage import (
    EVENT_COLUMNS,
    PostgresAgentTaskConflictError,
    root_for_session,
    segment_from_row,
    task_event_from_row,
)


class PostgresAgentTaskStore(AgentTaskPort):
    """Explicitly rebuilt Task index whose read methods never write."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

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
        with self._database.connect() as connection:
            return get_task_in_transaction(
                connection,
                self._database.deployment_namespace,
                task_id,
            )

    def list_tasks(self, *, limit: int) -> tuple[AgentTask, ...]:
        if limit <= 0:
            return ()
        with self._database.connect() as connection:
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

    def segments(self, task_id: TaskId) -> tuple[ExecutionSegment, ...]:
        with self._database.connect() as connection:
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

    def is_internal_segment(self, session_id: SessionId) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT task_id FROM execution_segments
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchone()
        return row is not None and row["task_id"] != session_id

    def attach_segment(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        *,
        predecessor_id: SessionId,
        reason: RolloverReason,
    ) -> AgentTask:
        with self._database.connect() as connection:
            attach_segment_in_transaction(
                connection,
                self._database.deployment_namespace,
                task_id=task_id,
                segment_id=segment_id,
                predecessor_id=predecessor_id,
                reason=reason,
            )
            return _require_task(connection, self._database.deployment_namespace, task_id)

    def read_events(self, task_id: TaskId, after_sequence: int) -> tuple[TaskEvent, ...]:
        if after_sequence < -1:
            raise ValueError("task event cursor must be greater than or equal to -1")
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT task_index.task_sequence, task_index.segment_id,
                       task_index.segment_sequence, {EVENT_COLUMNS}
                FROM task_event_index task_index
                JOIN session_events event
                  ON event.deployment_namespace = task_index.deployment_namespace
                 AND event.event_id = task_index.event_id
                WHERE task_index.deployment_namespace = %s
                  AND task_index.task_id = %s
                  AND task_index.task_sequence > %s
                ORDER BY task_index.task_sequence
                """,
                (self._database.deployment_namespace, task_id, after_sequence),
            ).fetchall()
        return tuple(task_event_from_row(task_id, row) for row in rows)

__all__ = [
    "PostgresAgentTaskConflictError",
    "PostgresAgentTaskStore",
    "attach_segment_in_transaction",
    "rebuild_task_in_transaction",
]
