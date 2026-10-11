"""Namespace-scoped PostgreSQL Task seek pages with pre-hydration byte admission."""

from typing import Any

from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import TaskEventPage

from agent_storage.postgres.task_lineage import (
    EVENT_COLUMNS,
    PostgresAgentTaskConflictError,
    task_event_from_row,
)
from agent_storage.task_event_page_limits import (
    admitted_page_positions,
    build_event_page,
    page_highwater,
    validate_page_request,
)


def read_task_event_page(
    connection: Any,
    namespace: str,
    task_id: TaskId,
    after: int,
    *,
    limit: int,
    max_bytes: int,
    through: int | None,
) -> TaskEventPage:
    validate_page_request(after, limit, max_bytes, through)
    header = connection.execute(
        """SELECT next_event_sequence,event_position_state FROM agent_tasks
           WHERE deployment_namespace=%s AND task_id=%s""",
        (namespace, task_id),
    ).fetchone()
    if header is None:
        raise PostgresAgentTaskConflictError("Task page target was not found")
    if header["event_position_state"] != "ready":
        raise PostgresAgentTaskConflictError("Task Event positions require explicit backfill")
    highwater = page_highwater(after, header["next_event_sequence"], through)
    metadata = connection.execute(
        """SELECT event.task_sequence,member.task_id AS member_task,
                  event.event_bytes_bound AS source_bytes
           FROM session_events event LEFT JOIN execution_segments member
             ON member.deployment_namespace=event.deployment_namespace
            AND member.session_id=event.session_id
           WHERE event.deployment_namespace=%s AND event.task_id=%s
             AND event.task_sequence>%s AND event.task_sequence<=%s
           ORDER BY event.task_sequence LIMIT %s""",
        (namespace, task_id, after, highwater, limit),
    ).fetchall()
    if any(row["member_task"] != task_id for row in metadata):
        raise PostgresAgentTaskConflictError("canonical Task page conflicts with membership")
    if any(row["source_bytes"] is None for row in metadata):
        raise PostgresAgentTaskConflictError("Event byte bounds require explicit backfill")
    positions = admitted_page_positions(
        [(row["task_sequence"], row["source_bytes"]) for row in metadata],
        after=after,
        highwater=highwater,
        max_bytes=max_bytes,
    )
    if not positions:
        return build_event_page((), after=after, highwater=highwater, max_bytes=max_bytes)
    rows = connection.execute(
        f"""SELECT event.task_sequence,event.session_id AS segment_id,
                   event.sequence AS segment_sequence,{EVENT_COLUMNS}
            FROM session_events event WHERE event.deployment_namespace=%s AND event.task_id=%s
              AND event.task_sequence>%s AND event.task_sequence<=%s
            ORDER BY event.task_sequence LIMIT %s""",
        (namespace, task_id, after, positions[-1], len(positions)),
    ).fetchall()
    events = tuple(task_event_from_row(task_id, row) for row in rows)
    if len(events) != len(positions):
        raise PostgresAgentTaskConflictError("canonical Task page changed during its bounded read")
    return build_event_page(events, after=after, highwater=highwater, max_bytes=max_bytes)
