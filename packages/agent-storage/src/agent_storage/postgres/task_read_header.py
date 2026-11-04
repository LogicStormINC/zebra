"""Bounded Task header, including explicit control-plane terminal authority."""

from typing import Any

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_core.ports.task_replay import TaskReadHeader


def read_task_header(
    connection: Any,
    namespace: str,
    task_id: TaskId | None = None,
    *,
    member_session_id: SessionId | None = None,
    require_source_coverage: bool = False,
) -> TaskReadHeader | None:
    if (task_id is None) == (member_session_id is None):
        raise ValueError("Task header requires exactly one lookup coordinate")
    # Both predicates use the native namespace-qualified identity indexes.
    parameters: tuple[object, ...]
    if member_session_id is None:
        coordinate = "t.task_id=%s"
        parameters = (namespace, task_id)
    else:
        coordinate = (
            "t.task_id=(SELECT task_id FROM execution_segments "
            "WHERE deployment_namespace=%s AND session_id=%s)"
        )
        parameters = (namespace, namespace, member_session_id)
    row = connection.execute(
        "SELECT t.task_id,t.active_segment_id,t.next_event_sequence,t.event_position_state,"
        "h.title,h.status,h.current_sequence AS active_segment_sequence,"
        "h.title_truncated,h.clarification_id,h.clarification_invalid,"
        "(o.kind IN ('dead_letter','watchdog','zombie_repair') AND NOT o.shadow) "
        "AS safety_terminal,o.reason AS safety_reason "
        "FROM agent_tasks t LEFT JOIN session_observation_headers h "
        "ON h.deployment_namespace=t.deployment_namespace "
        "AND h.session_id=t.active_segment_id::text "
        "LEFT JOIN agent_safety_overrides o "
        "ON o.deployment_namespace=t.deployment_namespace "
        "AND o.session_id::text=t.active_segment_id::text "
        f"WHERE t.deployment_namespace=%s AND {coordinate}",
        parameters,
    ).fetchone()
    if row is None:
        return None
    task_id = TaskId(row["task_id"])
    if row["safety_terminal"]:
        # A control-plane terminal override is authoritative even when the
        # event projection is missing or stale: readers must always see a
        # terminal header for dead-lettered/watchdog/zombie sessions instead
        # of an endless projection_not_ready 409.
        return TaskReadHeader(
            task_id,
            SessionId(row["active_segment_id"]),
            row["next_event_sequence"] - 1,
            title=row["title"],
            status=(
                SessionStatus(row["status"])
                if row["safety_reason"] == "user_force_stop"
                and row["status"] in {"completed", "failed"}
                else SessionStatus.CANCELLED
                if row["safety_reason"] == "user_force_stop"
                else SessionStatus.FAILED
            ),
            active_segment_sequence=row["active_segment_sequence"],
            title_truncated=bool(row["title_truncated"]),
            clarification_id=row["clarification_id"],
            clarification_invalid=bool(row["clarification_invalid"]),
        )
    strict_coverage = None
    if require_source_coverage:
        from agent_storage.postgres.stream_read_preflight import require_stream_source

        if row["event_position_state"] != "ready":
            raise CheckpointNotReady("Task Event positions require explicit backfill")
        if row["status"] is None or row["active_segment_sequence"] is None:
            raise CheckpointNotReady("stream observation header requires explicit preparation")
        strict_coverage = require_stream_source(connection, namespace, task_id, row)
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
        strict_coverage=strict_coverage,
    )
