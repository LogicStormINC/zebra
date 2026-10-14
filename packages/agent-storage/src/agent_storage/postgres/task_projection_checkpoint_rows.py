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


CHECKPOINT_HEAD_BODY = """
task AS (SELECT next_event_sequence,event_position_state FROM agent_tasks,args a
          WHERE deployment_namespace=a.ns AND task_id=a.tid AND a.enabled),
        head AS (SELECT h.through_sequence,h.last_event_id,
          h.latest_eligible_sequence,h.terminal_sequence
          FROM task_projection_heads h,args a WHERE h.deployment_namespace=a.ns AND h.task_id=a.tid
          AND h.anchor_key=a.anchor AND h.projector_version=a.version),
        frames AS (SELECT f.task_sequence,f.event_id,f.segment_id,f.segment_sequence,
          f.state_before_sequence,f.frame_count,f.projected,f.eligible
          FROM task_projection_frames f,args a,head h
          WHERE f.deployment_namespace=a.ns AND f.task_id=a.tid AND f.anchor_key=a.anchor
          AND f.projector_version=a.version
          AND f.task_sequence IN (h.latest_eligible_sequence,h.terminal_sequence)),
        locators AS (SELECT task_sequence,event_id,segment_id,segment_sequence FROM frames
          UNION ALL SELECT through_sequence,last_event_id,NULL::uuid,NULL::bigint
          FROM head WHERE through_sequence>=0),
        anchor AS (SELECT e.task_id,e.task_sequence,e.sequence,m.task_id AS member_task,
          m.event_position_source_ready,m.event_position_source_cursor
          FROM args a LEFT JOIN session_events e ON e.deployment_namespace=a.ns
          AND e.event_id=NULLIF(a.anchor,'')::uuid LEFT JOIN execution_segments m
          ON m.deployment_namespace=a.ns AND m.session_id=e.session_id)
        SELECT t.*,(SELECT to_jsonb(h) FROM head h) AS head,
          (SELECT jsonb_agg(to_jsonb(f)) FROM frames f) AS frames,
          EXISTS(SELECT 1 FROM anchor x,args a WHERE a.anchor<>'' AND (
            x.task_id IS DISTINCT FROM a.tid OR x.member_task IS DISTINCT FROM a.tid
            OR x.task_sequence IS NULL OR x.task_sequence>=t.next_event_sequence
            OR x.event_position_source_ready IS DISTINCT FROM true
            OR x.sequence>x.event_position_source_cursor)) AS invalid_anchor,
          EXISTS(SELECT 1 FROM locators l CROSS JOIN args a
            LEFT JOIN session_events e ON e.deployment_namespace=a.ns AND e.task_id=a.tid
            AND e.task_sequence=l.task_sequence LEFT JOIN execution_segments m
            ON m.deployment_namespace=a.ns AND m.session_id=e.session_id
            WHERE e.event_id IS NULL OR m.task_id IS DISTINCT FROM a.tid
            OR m.event_position_source_ready IS DISTINCT FROM true
            OR e.sequence>m.event_position_source_cursor OR e.event_id IS DISTINCT FROM l.event_id
            OR (l.segment_id IS NOT NULL AND e.session_id IS DISTINCT FROM l.segment_id)
            OR (l.segment_sequence IS NOT NULL AND e.sequence IS DISTINCT FROM l.segment_sequence)
          ) AS invalid_source FROM task t"""


def head_at(connection: Connection, scope: ProjectionScope) -> ProjectionCheckpointHead:
    row = connection.execute(
        "SELECT * FROM (WITH args AS (SELECT %s::text ns,%s::uuid tid,"
        "%s::text anchor,%s::text version,true AS enabled)," + CHECKPOINT_HEAD_BODY + ") metadata",
        scope_values(scope),
    ).fetchone()
    return checkpoint_head_from_row(row, scope)


def checkpoint_head_from_row(row: Any, scope: ProjectionScope) -> ProjectionCheckpointHead:
    if row is None:
        raise CheckpointConflict("checkpoint Task namespace is unavailable")
    if row["event_position_state"] != "ready":
        raise CheckpointNotReady("canonical Task positions require explicit backfill")
    if row["invalid_anchor"]:
        raise CheckpointConflict("checkpoint anchor conflicts with canonical Task source")
    head = row["head"]
    if head is None:
        return ProjectionCheckpointHead(scope)
    if head["through_sequence"] >= row["next_event_sequence"]:
        raise CheckpointConflict("checkpoint frontier exceeds canonical source coverage")
    if row["invalid_source"]:
        raise CheckpointConflict("checkpoint locator conflicts with canonical source")
    frames = {frame["task_sequence"]: json_frame_header(frame) for frame in row["frames"] or []}
    latest = frames.get(head["latest_eligible_sequence"])
    terminal = frames.get(head["terminal_sequence"])
    if (head["latest_eligible_sequence"] is not None and latest is None) or (
        head["terminal_sequence"] is not None and terminal is None
    ):
        raise CheckpointConflict("checkpoint frontier references a missing frame header")
    return ProjectionCheckpointHead(
        scope,
        head["through_sequence"],
        EventId(UUID(head["last_event_id"])) if head["last_event_id"] else None,
        latest,
        terminal,
    )


def json_frame_header(row: Any) -> ProjectionFrameHeader:
    return ProjectionFrameHeader(
        row["task_sequence"],
        EventId(UUID(row["event_id"])),
        SessionId(UUID(row["segment_id"])),
        row["segment_sequence"],
        row["state_before_sequence"],
        row["frame_count"],
        row["projected"],
        row["eligible"],
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
