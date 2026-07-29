"""PostgreSQL Task-index transaction and row primitives."""

from typing import Any
from uuid import UUID

from agent_core.domain.agent_tasks import (
    AgentTask,
    RolloverReason,
)
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from psycopg import errors
from psycopg.rows import dict_row

from agent_storage.postgres.task_lineage import (
    PostgresAgentTaskConflictError,
    derive_lineage,
)


def rebuild_task_in_transaction(
    connection: Any,
    deployment_namespace: str,
    root_session_id: SessionId,
) -> AgentTask:
    """Rebuild one Event-derived Task index in the caller's transaction."""
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT 1")
            with connection.transaction():
                return _rebuild_task(cursor, deployment_namespace, root_session_id)
    except errors.UniqueViolation as exc:
        raise PostgresAgentTaskConflictError("task lineage conflicts with its index") from exc


def _rebuild_task(
    connection: Any,
    deployment_namespace: str,
    root_session_id: SessionId,
) -> AgentTask:
    task_id = TaskId(UUID(str(root_session_id)))
    _lock_task(connection, deployment_namespace, task_id)
    root = connection.execute(
        """
        SELECT created_at FROM session_projections
        WHERE deployment_namespace = %s AND session_id = %s
        """,
        (deployment_namespace, root_session_id),
    ).fetchone()
    if root is None:
        raise PostgresAgentTaskConflictError("task root Session was not found")
    lineage = derive_lineage(connection, deployment_namespace, root_session_id)
    active = lineage[-1]
    connection.execute(
        """
        INSERT INTO agent_tasks (
            deployment_namespace, task_id, root_session_id, active_segment_id,
            created_at, updated_at
        )
        SELECT %s, %s, %s, %s, %s, projection.updated_at
        FROM session_projections projection
        WHERE projection.deployment_namespace = %s AND projection.session_id = %s
        ON CONFLICT (deployment_namespace, task_id) DO UPDATE SET
            active_segment_id = EXCLUDED.active_segment_id,
            updated_at = EXCLUDED.updated_at
        """,
        (
            deployment_namespace,
            task_id,
            root_session_id,
            active["session_id"],
            root["created_at"],
            deployment_namespace,
            active["session_id"],
        ),
    )
    connection.execute(
        """
        SELECT task_id FROM agent_tasks
        WHERE deployment_namespace = %s AND task_id = %s
        FOR UPDATE
        """,
        (deployment_namespace, task_id),
    ).fetchone()
    connection.execute(
        """
        DELETE FROM task_event_index
        WHERE deployment_namespace = %s AND task_id = %s
        """,
        (deployment_namespace, task_id),
    )
    connection.execute(
        """
        DELETE FROM execution_segments
        WHERE deployment_namespace = %s AND task_id = %s
        """,
        (deployment_namespace, task_id),
    )
    for row in lineage:
        connection.execute(
            """
            INSERT INTO execution_segments (
                deployment_namespace, session_id, task_id, predecessor_id,
                segment_index, visibility, rollover_reason
            ) VALUES (%s, %s, %s, %s, %s, 'internal', %s)
            ON CONFLICT (deployment_namespace, session_id) DO UPDATE SET
                task_id = EXCLUDED.task_id,
                predecessor_id = EXCLUDED.predecessor_id,
                segment_index = EXCLUDED.segment_index,
                visibility = EXCLUDED.visibility,
                rollover_reason = EXCLUDED.rollover_reason
            """,
            (
                deployment_namespace,
                row["session_id"],
                task_id,
                row["predecessor_id"],
                row["segment_index"],
                row["rollover_reason"],
            ),
        )
    _sync_events_in_transaction(connection, deployment_namespace, task_id)
    return _require_task(connection, deployment_namespace, task_id)


def attach_segment_in_transaction(
    connection: Any,
    deployment_namespace: str,
    *,
    task_id: TaskId,
    segment_id: SessionId,
    predecessor_id: SessionId,
    reason: RolloverReason,
) -> None:
    """CAS one rollover using a transaction owned by this or a Handoff adapter."""
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT 1")
            with connection.transaction():
                _attach_segment(
                    cursor,
                    deployment_namespace,
                    task_id=task_id,
                    segment_id=segment_id,
                    predecessor_id=predecessor_id,
                    reason=reason,
                )
    except errors.UniqueViolation as exc:
        raise PostgresAgentTaskConflictError("rollover conflicts with Task lineage") from exc


def _attach_segment(
    connection: Any,
    deployment_namespace: str,
    *,
    task_id: TaskId,
    segment_id: SessionId,
    predecessor_id: SessionId,
    reason: RolloverReason,
) -> None:
    _lock_task(connection, deployment_namespace, task_id)
    active = connection.execute(
        """
        SELECT active_segment_id FROM agent_tasks
        WHERE deployment_namespace = %s AND task_id = %s
        FOR UPDATE
        """,
        (deployment_namespace, task_id),
    ).fetchone()
    if active is None or active["active_segment_id"] != predecessor_id:
        raise PostgresAgentTaskConflictError("task active Segment changed during rollover")
    predecessor = connection.execute(
        """
        SELECT segment_index FROM execution_segments
        WHERE deployment_namespace = %s AND task_id = %s AND session_id = %s
        """,
        (deployment_namespace, task_id, predecessor_id),
    ).fetchone()
    if predecessor is None:
        raise PostgresAgentTaskConflictError("rollover predecessor is not indexed")
    child = connection.execute(
        """
        SELECT updated_at FROM session_projections
        WHERE deployment_namespace = %s AND session_id = %s
        """,
        (deployment_namespace, segment_id),
    ).fetchone()
    if child is None:
        raise PostgresAgentTaskConflictError("rollover Segment projection was not found")
    connection.execute(
        """
        INSERT INTO execution_segments (
            deployment_namespace, session_id, task_id, predecessor_id,
            segment_index, visibility, rollover_reason
        ) VALUES (%s, %s, %s, %s, %s, 'internal', %s)
        """,
        (
            deployment_namespace,
            segment_id,
            task_id,
            predecessor_id,
            predecessor["segment_index"] + 1,
            reason.value,
        ),
    )
    updated = connection.execute(
        """
        UPDATE agent_tasks
        SET active_segment_id = %s, updated_at = %s
        WHERE deployment_namespace = %s AND task_id = %s AND active_segment_id = %s
        """,
        (segment_id, child["updated_at"], deployment_namespace, task_id, predecessor_id),
    )
    if updated.rowcount != 1:
        raise PostgresAgentTaskConflictError("task active Segment CAS failed")
    _sync_events_in_transaction(connection, deployment_namespace, task_id)


def get_task_in_transaction(
    connection: Any,
    deployment_namespace: str,
    task_id: TaskId,
) -> AgentTask | None:
    row = connection.execute(
        """
        SELECT task.task_id, task.active_segment_id, projection.title,
               projection.status, projection.current_sequence AS segment_sequence,
               COALESCE(MAX(task_index.task_sequence), -1) AS task_sequence
        FROM agent_tasks task
        JOIN session_projections projection
          ON projection.deployment_namespace = task.deployment_namespace
         AND projection.session_id = task.active_segment_id
        LEFT JOIN task_event_index task_index
          ON task_index.deployment_namespace = task.deployment_namespace
         AND task_index.task_id = task.task_id
        WHERE task.deployment_namespace = %s AND task.task_id = %s
        GROUP BY task.task_id, task.active_segment_id, projection.title,
                 projection.status, projection.current_sequence
        """,
        (deployment_namespace, task_id),
    ).fetchone()
    if row is None:
        return None
    return AgentTask(
        task_id=TaskId(row["task_id"]),
        title=row["title"],
        status=SessionStatus(row["status"]),
        active_segment_id=SessionId(row["active_segment_id"]),
        current_sequence=max(row["task_sequence"], row["segment_sequence"]),
        namespace=deployment_namespace,
    )


def _require_task(connection: Any, namespace: str, task_id: TaskId) -> AgentTask:
    task = get_task_in_transaction(connection, namespace, task_id)
    if task is None:
        raise PostgresAgentTaskConflictError("task projection is incomplete")
    return task


def _sync_events_in_transaction(
    connection: Any,
    deployment_namespace: str,
    task_id: TaskId,
) -> None:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(task_sequence), -1) + 1 AS next_sequence
        FROM task_event_index
        WHERE deployment_namespace = %s AND task_id = %s
        """,
        (deployment_namespace, task_id),
    ).fetchone()
    next_sequence = row["next_sequence"]
    events = connection.execute(
        """
        SELECT event.event_id, event.session_id, event.sequence
        FROM execution_segments segment
        JOIN session_events event
          ON event.deployment_namespace = segment.deployment_namespace
         AND event.session_id = segment.session_id
        LEFT JOIN task_event_index indexed
          ON indexed.deployment_namespace = event.deployment_namespace
         AND indexed.event_id = event.event_id
        WHERE segment.deployment_namespace = %s AND segment.task_id = %s
          AND indexed.event_id IS NULL
        ORDER BY segment.segment_index, event.sequence
        """,
        (deployment_namespace, task_id),
    ).fetchall()
    for event in events:
        connection.execute(
            """
            INSERT INTO task_event_index (
                deployment_namespace, task_id, task_sequence, event_id,
                segment_id, segment_sequence
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                deployment_namespace,
                task_id,
                next_sequence,
                event["event_id"],
                event["session_id"],
                event["sequence"],
            ),
        )
        next_sequence += 1


def _lock_task(connection: Any, namespace: str, task_id: TaskId) -> None:
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"{namespace}:{task_id}",),
    ).fetchone()
