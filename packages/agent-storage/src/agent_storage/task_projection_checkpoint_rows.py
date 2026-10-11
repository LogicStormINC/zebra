"""Small typed checkpoint records and request admission, never historical bodies."""

import sqlite3
from uuid import UUID

from agent_core.domain.identifiers import EventId, SessionId
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_BYTES,
    MAX_CHECKPOINT_KEYS,
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    SegmentCheckpoint,
)

SCOPE_WHERE = "deployment_namespace=? AND task_id=? AND anchor_key=? AND projector_version=?"


def scope_values(scope: ProjectionScope) -> tuple[str, str, str, str]:
    return (
        scope.namespace,
        str(scope.task_id),
        str(scope.anchor_event_id) if scope.anchor_event_id else "",
        scope.projector_version,
    )


def require_scope(connection: sqlite3.Connection, scope: ProjectionScope) -> int:
    task = connection.execute(
        "SELECT namespace,event_position_state,next_event_sequence "
        "FROM agent_tasks WHERE task_id=?",
        (str(scope.task_id),),
    ).fetchone()
    if task is None or task["namespace"] != scope.namespace:
        raise CheckpointConflict("checkpoint Task namespace is unavailable")
    if task["event_position_state"] != "ready":
        raise CheckpointNotReady("canonical Task positions require explicit backfill")
    if scope.anchor_event_id is not None:
        anchor = connection.execute(
            """SELECT event.task_id,event.task_sequence,event.sequence,
                      member.task_id AS member_task,
                      member.event_position_source_cursor,member.event_position_source_ready
               FROM session_events event LEFT JOIN execution_segments member
                 ON member.session_id=event.session_id WHERE event.event_id=?""",
            (str(scope.anchor_event_id),),
        ).fetchone()
        if anchor is None or (
            anchor["task_id"] != str(scope.task_id)
            or anchor["member_task"] != str(scope.task_id)
            or anchor["task_sequence"] is None
            or anchor["task_sequence"] >= task["next_event_sequence"]
            or not anchor["event_position_source_ready"]
            or anchor["sequence"] > anchor["event_position_source_cursor"]
        ):
            raise CheckpointConflict("checkpoint anchor belongs to another Task")
    return int(task["next_event_sequence"])


def require_segments(
    connection: sqlite3.Connection, scope: ProjectionScope, segments: tuple[SessionId, ...]
) -> None:
    for segment in dict.fromkeys(segments):
        if not isinstance(segment, UUID):
            raise ValueError("invalid checkpoint Segment identity")
        row = connection.execute(
            "SELECT task_id FROM execution_segments WHERE session_id=?", (str(segment),)
        ).fetchone()
        if row is None or row["task_id"] != str(scope.task_id):
            raise CheckpointConflict("checkpoint Segment belongs to another Task")


def frame_from_row(row: sqlite3.Row) -> ProjectionFrameHeader:
    return ProjectionFrameHeader(
        row["task_sequence"],
        EventId(UUID(row["event_id"])),
        SessionId(UUID(row["segment_id"])),
        row["segment_sequence"],
        row["state_before_sequence"],
        row["frame_count"],
        bool(row["projected"]),
        bool(row["eligible"]),
    )


def frame_at(
    connection: sqlite3.Connection,
    scope: ProjectionScope,
    position: int | None,
) -> ProjectionFrameHeader | None:
    if position is None:
        return None
    row = connection.execute(
        f"SELECT * FROM task_projection_frames WHERE {SCOPE_WHERE} AND task_sequence=?",
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
    return frame_from_row(row)


def require_source(
    connection: sqlite3.Connection,
    scope: ProjectionScope,
    position: int,
    *,
    event_id: str | None = None,
    segment_id: str | None = None,
    segment_sequence: int | None = None,
) -> None:
    source = connection.execute(
        "SELECT event_id,session_id,sequence FROM session_events "
        "INDEXED BY session_events_scalar_header WHERE task_id=? AND task_sequence=?",
        (str(scope.task_id), position),
    ).fetchone()
    if source is None:
        raise CheckpointConflict("checkpoint locator conflicts with canonical source")
    require_source_member(
        connection,
        scope,
        source,
        event_id=event_id,
        segment_id=segment_id,
        segment_sequence=segment_sequence,
    )


def require_source_member(
    connection: sqlite3.Connection,
    scope: ProjectionScope,
    source: sqlite3.Row,
    *,
    event_id: str | None = None,
    segment_id: str | None = None,
    segment_sequence: int | None = None,
) -> None:
    """Validate a native canonical header row without repeating its point seek."""
    # ponytail: two indexed metadata points in the caller's snapshot keep the
    # source body off the read path; joining can select a non-covering source index.
    member = connection.execute(
        "SELECT task_id,event_position_source_ready,event_position_source_cursor "
        "FROM execution_segments WHERE session_id=?",
        (source["session_id"],),
    ).fetchone()
    if member is None or (
        member["task_id"] != str(scope.task_id)
        or not member["event_position_source_ready"]
        or source["sequence"] > member["event_position_source_cursor"]
        or (event_id is not None and source["event_id"] != event_id)
        or (segment_id is not None and source["session_id"] != segment_id)
        or (segment_sequence is not None and source["sequence"] != segment_sequence)
    ):
        raise CheckpointConflict("checkpoint locator conflicts with canonical source")


def head_at(connection: sqlite3.Connection, scope: ProjectionScope) -> ProjectionCheckpointHead:
    next_sequence = require_scope(connection, scope)
    row = connection.execute(
        f"SELECT * FROM task_projection_heads WHERE {SCOPE_WHERE}",
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
        EventId(UUID(row["last_event_id"])) if row["last_event_id"] else None,
        latest,
        terminal,
    )


def read_position(head: ProjectionCheckpointHead, position: int, *, before: bool = False) -> None:
    if type(position) is not int or not 0 <= position <= 9_223_372_036_854_775_807:
        raise ValueError("invalid checkpoint read position")
    if position > head.through_sequence + int(before):
        raise CheckpointNotReady("checkpoint frontier has not reached the requested position")


def scalar_before(
    connection: sqlite3.Connection,
    scope: ProjectionScope,
    segment: SessionId,
    before: int,
) -> SegmentCheckpoint:
    row = connection.execute(
        f"SELECT * FROM task_projection_scalars WHERE {SCOPE_WHERE} "
        "AND segment_id=? AND task_sequence<? ORDER BY task_sequence DESC LIMIT 1",
        (*scope_values(scope), str(segment), before),
    ).fetchone()
    if row is not None:
        require_source(
            connection,
            scope,
            row["task_sequence"],
            segment_id=str(segment),
            segment_sequence=row["segment_sequence"],
        )
    return (
        SegmentCheckpoint(segment, -1, -1, False, False)
        if row is None
        else SegmentCheckpoint(
            segment,
            row["task_sequence"],
            row["segment_sequence"],
            bool(row["started"]),
            bool(row["turn_finished"]),
        )
    )


def validate_keys(keys: tuple[ProjectionCellKey, ...]) -> None:
    if type(keys) is not tuple or len(keys) > MAX_CHECKPOINT_KEYS or len(set(keys)) != len(keys):
        raise ValueError("checkpoint keys exceed bound or contain duplicates")
    if 512 + sum(256 + 6 * len(key.key.encode()) for key in keys) > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint key request exceeds byte bound")


def cell_bytes(key: ProjectionCellKey, value: str | None) -> int:
    return 256 + 6 * len(key.key.encode()) + 6 * len((value or "").encode())
