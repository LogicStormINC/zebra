"""Canonical Task membership and active-target CAS after the Session boundary."""

from typing import Any

from agent_core.domain.identifiers import SessionId, TaskId
from psycopg.errors import LockNotAvailable


def require_task_control_target(
    connection: Any, namespace: str, task_id: TaskId, session_id: SessionId, *, replay: bool
) -> None:
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
        # A former root Session can also be the Task advisory key. Never wait
        # here on a successor rollover holding the Task row and needing that key.
        raise ValueError("Task cancellation target is busy") from None
    if row is None or (not replay and row["active_segment_id"] != session_id):
        raise ValueError("Task cancellation target changed")
