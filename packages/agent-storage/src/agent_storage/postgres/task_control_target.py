"""Canonical Task membership and active-target CAS after the Session boundary."""

from typing import Any

from agent_core.domain.identifiers import SessionId, TaskId
from psycopg.errors import LockNotAvailable


def require_task_control_target(
    connection: Any, namespace: str, task_id: TaskId, session_id: SessionId, *, replay: bool
) -> None:
    # Never hold the Task row while waiting for an Event-position allocator.
    # Session/lease/stream locks were taken by the caller; Task serialization is last.
    acquired = connection.execute(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,61)) AS acquired",
        (f"{namespace}:{task_id}",),
    ).fetchone()
    if not acquired["acquired"]:
        raise ValueError("Task cancellation target is busy")
    try:
        row = connection.execute(
            """SELECT task.active_segment_id FROM agent_tasks task
            JOIN execution_segments segment
            ON segment.deployment_namespace=task.deployment_namespace
            AND segment.task_id=task.task_id WHERE task.deployment_namespace=%s
            AND task.task_id=%s AND segment.session_id=%s FOR UPDATE OF task NOWAIT""",
            (namespace, task_id, session_id),
        ).fetchone()
    except LockNotAvailable:
        # A writer outside this protocol may still hold the Task row. Fail closed.
        raise ValueError("Task cancellation target is busy") from None
    if row is None or (not replay and row["active_segment_id"] != session_id):
        raise ValueError("Task cancellation target changed")
