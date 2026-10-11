"""Bounded metadata validation and point reads for PostgreSQL checkpoints."""

from typing import Any
from uuid import UUID

import psycopg
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)

Connection = psycopg.Connection[dict[str, Any]]
SCOPE_WHERE = "deployment_namespace=%s AND task_id=%s AND anchor_key=%s AND projector_version=%s"
FRAME_COLUMNS = (
    "task_sequence,event_id,segment_id,segment_sequence,state_before_sequence,"
    "frame_count,projected,eligible"
)


def scope_values(scope: ProjectionScope) -> tuple[str, TaskId, str, str]:
    return (
        scope.namespace,
        scope.task_id,
        str(scope.anchor_event_id) if scope.anchor_event_id is not None else "",
        scope.projector_version,
    )


def require_scope(connection: Connection, scope: ProjectionScope) -> int:
    task = connection.execute(
        """SELECT next_event_sequence,event_position_state FROM agent_tasks
           WHERE deployment_namespace=%s AND task_id=%s""",
        (scope.namespace, scope.task_id),
    ).fetchone()
    if task is None:
        raise CheckpointConflict("checkpoint Task namespace is unavailable")
    if task["event_position_state"] != "ready":
        raise CheckpointNotReady("canonical Task positions require explicit backfill")
    if scope.anchor_event_id is not None:
        row = connection.execute(
            """SELECT event.task_id,event.task_sequence,event.sequence,
                      member.task_id AS member_task,member.event_position_source_cursor,
                      member.event_position_source_ready FROM session_events event
               LEFT JOIN LATERAL (SELECT task_id,event_position_source_cursor,
                                        event_position_source_ready FROM execution_segments
                 WHERE deployment_namespace=%s AND session_id=event.session_id
                 LIMIT 1) member ON true
               WHERE event.deployment_namespace=%s AND event.event_id=%s""",
            (scope.namespace, scope.namespace, scope.anchor_event_id),
        ).fetchone()
        if row is None or (
            row["task_id"] != scope.task_id
            or row["member_task"] != scope.task_id
            or row["task_sequence"] is None
            or row["task_sequence"] >= task["next_event_sequence"]
            or not row["event_position_source_ready"]
            or row["sequence"] > row["event_position_source_cursor"]
        ):
            raise CheckpointConflict("checkpoint anchor conflicts with canonical Task source")
    return int(task["next_event_sequence"])


def require_segments(
    connection: Connection,
    scope: ProjectionScope,
    segments: tuple[SessionId, ...],
) -> None:
    if any(not isinstance(segment, UUID) for segment in segments):
        raise ValueError("invalid checkpoint Segment identity")
    if not segments:
        return
    rows = connection.execute(
        """SELECT member.task_id FROM unnest(%s::uuid[]) requested(segment_id)
           LEFT JOIN LATERAL (SELECT task_id FROM execution_segments
             WHERE deployment_namespace=%s AND session_id=requested.segment_id
             LIMIT 1) member ON true""",
        (list(dict.fromkeys(segments)), scope.namespace),
    ).fetchall()
    if any(row["task_id"] != scope.task_id for row in rows):
        raise CheckpointConflict("checkpoint Segment belongs to another Task")


def frame_at(
    connection: Connection,
    scope: ProjectionScope,
    position: int | None,
) -> ProjectionFrameHeader | None:
    if position is None:
        return None
    row = connection.execute(
        f"""SELECT {FRAME_COLUMNS} FROM task_projection_frames
            WHERE {SCOPE_WHERE} AND task_sequence=%s""",
        (*scope_values(scope), position),
    ).fetchone()
    if row is None:
        return None
    require_source(
        connection,
        scope,
        position,
        event_id=row["event_id"],
        segment_id=row["segment_id"],
        segment_sequence=row["segment_sequence"],
    )
    return ProjectionFrameHeader(
        row["task_sequence"],
        EventId(row["event_id"]),
        SessionId(row["segment_id"]),
        row["segment_sequence"],
        row["state_before_sequence"],
        row["frame_count"],
        row["projected"],
        row["eligible"],
    )


def require_source(
    connection: Connection,
    scope: ProjectionScope,
    position: int,
    *,
    event_id: UUID | None = None,
    segment_id: UUID | None = None,
    segment_sequence: int | None = None,
) -> None:
    row = connection.execute(
        """SELECT event.event_id,event.session_id,event.sequence,
                  member.task_id,member.event_position_source_ready,
                  member.event_position_source_cursor FROM session_events event
           LEFT JOIN LATERAL (SELECT task_id,event_position_source_ready,
                                    event_position_source_cursor FROM execution_segments
             WHERE deployment_namespace=%s AND session_id=event.session_id LIMIT 1) member ON true
           WHERE event.deployment_namespace=%s AND event.task_id=%s AND event.task_sequence=%s""",
        (scope.namespace, scope.namespace, scope.task_id, position),
    ).fetchone()
    if row is None or (
        row["task_id"] != scope.task_id
        or not row["event_position_source_ready"]
        or row["sequence"] > row["event_position_source_cursor"]
        or (event_id is not None and row["event_id"] != event_id)
        or (segment_id is not None and row["session_id"] != segment_id)
        or (segment_sequence is not None and row["sequence"] != segment_sequence)
    ):
        raise CheckpointConflict("checkpoint locator conflicts with canonical source")


def head_at(connection: Connection, scope: ProjectionScope) -> ProjectionCheckpointHead:
    next_sequence = require_scope(connection, scope)
    row = connection.execute(
        f"""SELECT through_sequence,last_event_id,latest_eligible_sequence,terminal_sequence
            FROM task_projection_heads WHERE {SCOPE_WHERE}""",
        scope_values(scope),
    ).fetchone()
    if row is None:
        return ProjectionCheckpointHead(scope)
    if row["through_sequence"] >= next_sequence:
        raise CheckpointConflict("checkpoint frontier exceeds canonical source coverage")
    latest = frame_at(connection, scope, row["latest_eligible_sequence"])
    terminal = frame_at(connection, scope, row["terminal_sequence"])
    if (row["latest_eligible_sequence"] is not None and latest is None) or (
        row["terminal_sequence"] is not None and terminal is None
    ):
        raise CheckpointConflict("checkpoint frontier references a missing frame header")
    if row["through_sequence"] >= 0:
        require_source(
            connection,
            scope,
            row["through_sequence"],
            event_id=row["last_event_id"],
        )
    return ProjectionCheckpointHead(
        scope,
        row["through_sequence"],
        EventId(row["last_event_id"]) if row["last_event_id"] is not None else None,
        latest,
        terminal,
    )


def scalar_before(
    connection: Connection,
    scope: ProjectionScope,
    segment: SessionId,
    before: int,
) -> SegmentCheckpoint:
    row = connection.execute(
        f"""SELECT task_sequence,segment_sequence,started,turn_finished
            FROM task_projection_scalars WHERE {SCOPE_WHERE}
            AND segment_id=%s AND task_sequence<%s ORDER BY task_sequence DESC LIMIT 1""",
        (*scope_values(scope), segment, before),
    ).fetchone()
    if row is not None:
        require_source(
            connection,
            scope,
            row["task_sequence"],
            segment_id=segment,
            segment_sequence=row["segment_sequence"],
        )
    return (
        SegmentCheckpoint(segment, -1, -1, False, False)
        if row is None
        else SegmentCheckpoint(
            segment,
            row["task_sequence"],
            row["segment_sequence"],
            row["started"],
            row["turn_finished"],
        )
    )


def validate_transition(
    connection: Connection, transition: ProjectionTransition, next_sequence: int
) -> None:
    scope = transition.scope
    if transition.through_sequence >= next_sequence:
        raise CheckpointConflict("checkpoint Page exceeds canonical source coverage")
    rows = connection.execute(
        """SELECT event.task_sequence,event.event_id,event.session_id,event.sequence,
                  member.task_id AS member_task,member.event_position_source_ready,
                  member.event_position_source_cursor FROM session_events event
           LEFT JOIN LATERAL (SELECT task_id,event_position_source_ready,
                                    event_position_source_cursor
             FROM execution_segments WHERE deployment_namespace=%s AND session_id=event.session_id
             LIMIT 1) member ON true
           WHERE event.deployment_namespace=%s AND event.task_id=%s
             AND event.task_sequence>%s AND event.task_sequence<=%s
           ORDER BY event.task_sequence LIMIT %s""",
        (
            scope.namespace,
            scope.namespace,
            scope.task_id,
            transition.expected_through,
            transition.through_sequence,
            len(transition.headers),
        ),
    ).fetchall()
    if len(rows) != len(transition.headers):
        raise CheckpointConflict("checkpoint Page has incomplete canonical source coverage")
    for header, row in zip(transition.headers, rows, strict=True):
        if (
            (header.task_sequence, header.event_id, header.segment_id, header.segment_sequence)
            != (
                row["task_sequence"],
                row["event_id"],
                row["session_id"],
                row["sequence"],
            )
            or row["member_task"] != scope.task_id
            or not row["event_position_source_ready"]
            or (row["sequence"] > row["event_position_source_cursor"])
        ):
            raise CheckpointConflict("checkpoint header conflicts with canonical source")
    scalars = {scalar.task_sequence: scalar for scalar in transition.scalars}
    predecessors: dict[SessionId, SegmentCheckpoint] = {}
    for header in transition.headers:
        if not header.projected:
            continue
        previous = predecessors.get(header.segment_id)
        if previous is None:
            previous = scalar_before(
                connection, scope, header.segment_id, transition.expected_through + 1
            )
        if (
            previous.task_sequence != header.state_before_sequence
            or previous.segment_sequence >= header.segment_sequence
        ):
            raise CheckpointConflict("checkpoint scalar predecessor conflicts with Event header")
        predecessors[header.segment_id] = scalars[header.task_sequence]
