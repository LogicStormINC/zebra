"""One atomic derived-page append; no source rewrite or execution authority."""

import sqlite3

from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
    ProjectionCheckpointHead,
    ProjectionTransition,
)

from agent_storage.task_projection_checkpoint_rows import (
    SCOPE_WHERE,
    cell_bytes,
    head_at,
    require_scope,
    require_segments,
    scalar_before,
    scope_values,
)


def commit_page(
    connection: sqlite3.Connection,
    transition: ProjectionTransition,
) -> ProjectionCheckpointHead:
    # ponytail: SQLite serializes writes, as the existing local baseline does.
    # Cloud uses a per-scope PostgreSQL head lock instead of this database lock.
    connection.execute("BEGIN IMMEDIATE")
    scope = transition.scope
    next_sequence = require_scope(connection, scope)
    if transition.through_sequence >= next_sequence:
        raise CheckpointConflict("checkpoint Page exceeds canonical source coverage")
    require_segments(connection, scope, tuple(h.segment_id for h in transition.headers))
    standard = [c for c in transition.cells if c.key.kind == "standard_v1"]
    if standard:
        anchor = connection.execute(
            "SELECT session_id FROM session_events WHERE task_id=? AND event_id=?",
            (str(scope.task_id), str(scope.anchor_event_id)),
        ).fetchone()
        if anchor is None or any(str(c.key.segment_id) != anchor["session_id"] for c in standard):
            raise CheckpointConflict("standard state must use the canonical root Segment")
    values = scope_values(scope)
    previous = head_at(connection, scope)
    if previous.through_sequence > transition.expected_through:
        raise CheckpointStale("checkpoint frontier CAS advanced before commit")
    if previous.through_sequence != transition.expected_through:
        raise CheckpointConflict("checkpoint frontier CAS failed")
    rows = connection.execute(
        "SELECT event.task_sequence,event.event_id,event.session_id,event.sequence,"
        "member.task_id AS member_task,member.event_position_source_ready,"
        "member.event_position_source_cursor FROM session_events event "
        "LEFT JOIN execution_segments member ON member.session_id=event.session_id "
        "WHERE event.task_id=? AND event.task_sequence>? AND event.task_sequence<=? "
        "ORDER BY event.task_sequence LIMIT 256",
        (str(scope.task_id), transition.expected_through, transition.through_sequence),
    ).fetchall()
    coordinates = tuple(
        (row["task_sequence"], row["event_id"], row["session_id"], row["sequence"]) for row in rows
    )
    expected = tuple(
        (h.task_sequence, str(h.event_id), str(h.segment_id), h.segment_sequence)
        for h in transition.headers
    )
    if coordinates != expected:
        raise CheckpointConflict("checkpoint page conflicts with canonical source Events")
    if any(row["member_task"] != str(scope.task_id) for row in rows):
        raise CheckpointConflict("checkpoint Page Segment belongs to another Task")
    if any(
        not row["event_position_source_ready"]
        or row["sequence"] > row["event_position_source_cursor"]
        for row in rows
    ):
        raise CheckpointNotReady("checkpoint Page exceeds ready Segment source coverage")
    connection.execute(
        "INSERT INTO task_projection_heads "
        "(deployment_namespace,task_id,anchor_key,projector_version) VALUES (?,?,?,?) "
        "ON CONFLICT DO NOTHING",
        values,
    )
    scalars = {row.task_sequence: row for row in transition.scalars}
    for header in transition.headers:
        if header.projected:
            scalar = scalar_before(connection, scope, header.segment_id, header.task_sequence)
            if header.state_before_sequence != scalar.task_sequence or (
                header.segment_sequence <= scalar.segment_sequence
            ):
                raise CheckpointConflict("checkpoint scalar predecessor conflicts")
        connection.execute(
            "INSERT INTO task_projection_frames VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                *values,
                header.task_sequence,
                str(header.event_id),
                str(header.segment_id),
                header.segment_sequence,
                header.state_before_sequence,
                header.frame_count,
                int(header.projected),
                int(header.eligible),
            ),
        )
        if header.projected:
            state = scalars[header.task_sequence]
            connection.execute(
                "INSERT INTO task_projection_scalars VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    *values,
                    str(state.segment_id),
                    state.task_sequence,
                    state.segment_sequence,
                    int(state.started),
                    int(state.turn_finished),
                ),
            )
    for cell in transition.cells:
        connection.execute(
            "INSERT INTO task_projection_cells VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                *values,
                str(cell.key.segment_id),
                cell.key.kind,
                cell.key.key,
                cell.task_sequence,
                cell.value,
                cell_bytes(cell.key, cell.value),
            ),
        )
    latest = next(
        (h.task_sequence for h in reversed(transition.headers) if h.eligible),
        previous.latest_eligible.task_sequence if previous.latest_eligible else None,
    )
    terminal = transition.terminal_sequence
    if terminal is None and previous.terminal is not None:
        terminal = previous.terminal.task_sequence
    cursor = connection.execute(
        f"UPDATE task_projection_heads SET through_sequence=?,last_event_id=?,"
        f"latest_eligible_sequence=?,terminal_sequence=? WHERE {SCOPE_WHERE} "
        "AND through_sequence=?",
        (
            transition.through_sequence,
            str(transition.headers[-1].event_id),
            latest,
            terminal,
            *values,
            transition.expected_through,
        ),
    )
    if cursor.rowcount != 1:
        raise CheckpointStale("checkpoint frontier CAS failed")
    return head_at(connection, scope)
