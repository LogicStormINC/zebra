"""Pure Task-lineage derivation and PostgreSQL row conversion."""

from typing import Any
from uuid import UUID

from agent_core.domain.agent_tasks import ExecutionSegment, RolloverReason, SegmentVisibility
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import TaskEvent


class PostgresAgentTaskConflictError(ValueError):
    """Raised when Task lineage or active-Segment CAS facts conflict."""


def root_for_session(
    connection: Any,
    deployment_namespace: str,
    session_id: SessionId,
) -> SessionId:
    rows = connection.execute(
        """
        SELECT projection.session_id, received.payload ->> 'root_session_id' AS root_session_id
        FROM session_projections projection
        LEFT JOIN session_events received
          ON received.deployment_namespace = projection.deployment_namespace
         AND received.session_id = projection.session_id
         AND received.event_type = %s
        WHERE projection.deployment_namespace = %s AND projection.session_id = %s
        """,
        (EventType.SESSION_HANDOFF_RECEIVED.value, deployment_namespace, session_id),
    ).fetchall()
    if not rows:
        raise PostgresAgentTaskConflictError("Session projection was not found")
    if len(rows) != 1:
        raise PostgresAgentTaskConflictError(
            "Session has ambiguous received Handoff lineage"
        )
    row = rows[0]
    raw = row["root_session_id"] or str(row["session_id"])
    return SessionId(UUID(raw))


def derive_lineage(
    connection: Any,
    deployment_namespace: str,
    root_session_id: SessionId,
) -> list[dict[str, Any]]:
    children = connection.execute(
        """
        SELECT projection.session_id,
               (received.payload ->> 'parent_session_id')::uuid AS predecessor_id,
               (received.payload ->> 'stage_index')::integer AS segment_index,
               committed.event_id AS committed_event_id,
               committed.match_count,
               committed.payload ->> 'reason' AS handoff_reason
        FROM session_projections projection
        JOIN session_events received
          ON received.deployment_namespace = projection.deployment_namespace
         AND received.session_id = projection.session_id
         AND received.event_type = %s
        LEFT JOIN LATERAL (
            SELECT event.event_id, event.payload, count(*) OVER () AS match_count
            FROM session_events event
            WHERE event.deployment_namespace = projection.deployment_namespace
              AND event.session_id = (received.payload ->> 'parent_session_id')::uuid
              AND event.event_type = %s
              AND event.payload ->> 'target_session_id' = projection.session_id::text
              AND event.payload ->> 'handoff_id' = received.payload ->> 'handoff_id'
              AND event.payload ->> 'target_stage_index' = received.payload ->> 'stage_index'
              AND event.payload ->> 'checksum' = received.payload ->> 'checksum'
              AND event.payload ->> 'artifact_id' = received.payload ->> 'artifact_id'
            ORDER BY event.sequence DESC
            LIMIT 1
        ) committed ON TRUE
        WHERE projection.deployment_namespace = %s
          AND received.payload ->> 'root_session_id' = %s
        ORDER BY segment_index, projection.session_id
        """,
        (
            EventType.SESSION_HANDOFF_RECEIVED.value,
            EventType.SESSION_HANDOFF_COMMITTED.value,
            deployment_namespace,
            str(root_session_id),
        ),
    ).fetchall()
    for row in children:
        if row["committed_event_id"] is None or row["match_count"] != 1:
            raise PostgresAgentTaskConflictError(
                "received Handoff does not match a committed parent Event"
            )
    rows = [
        {
            "session_id": root_session_id,
            "predecessor_id": None,
            "segment_index": 0,
            "rollover_reason": None,
        },
        *(
            {
                **row,
                "rollover_reason": _rollover_reason(row["handoff_reason"]).value,
            }
            for row in children
        ),
    ]
    _validate_lineage(root_session_id, rows)
    return rows


def segment_from_row(row: dict[str, Any]) -> ExecutionSegment:
    return ExecutionSegment(
        session_id=SessionId(row["session_id"]),
        task_id=TaskId(row["task_id"]),
        predecessor_id=(
            None if row["predecessor_id"] is None else SessionId(row["predecessor_id"])
        ),
        segment_index=row["segment_index"],
        visibility=SegmentVisibility(row["visibility"]),
        rollover_reason=(
            None
            if row["rollover_reason"] is None
            else RolloverReason(row["rollover_reason"])
        ),
    )


def task_event_from_row(task_id: TaskId, row: dict[str, Any]) -> TaskEvent:
    event_values = {key: row[key] for key in EVENT_FIELD_NAMES}
    return TaskEvent(
        task_id=task_id,
        task_sequence=row["task_sequence"],
        segment_id=SessionId(row["segment_id"]),
        segment_sequence=row["segment_sequence"],
        event=SessionEvent.model_validate(event_values),
    )


def _validate_lineage(root_session_id: SessionId, rows: list[dict[str, Any]]) -> None:
    previous = root_session_id
    for expected_index, row in enumerate(rows):
        if row["segment_index"] != expected_index:
            raise PostgresAgentTaskConflictError("task Segment indexes are not contiguous")
        if expected_index and row["predecessor_id"] != previous:
            raise PostgresAgentTaskConflictError("task Segment predecessor chain is not linear")
        previous = SessionId(row["session_id"])


def _rollover_reason(raw: str | None) -> RolloverReason:
    return {
        "internal_recovery": RolloverReason.RECOVERY,
        "internal_terminal_follow_up": RolloverReason.TERMINAL_FOLLOW_UP,
        "internal_agent_hint": RolloverReason.AGENT_HINT,
    }.get(raw or "", RolloverReason.CONTEXT_PRESSURE)


EVENT_FIELD_NAMES = (
    "event_id",
    "session_id",
    "sequence",
    "event_type",
    "payload",
    "actor",
    "created_at",
    "causation_id",
    "correlation_id",
    "idempotency_key",
    "policy_version",
    "model_profile",
)
EVENT_COLUMNS = ", ".join(f"event.{name}" for name in EVENT_FIELD_NAMES)
