"""SQLite source coordinates: bounded validation, adoption and index repair."""

import sqlite3

from agent_core.domain.identifiers import TaskId

from agent_storage.database import ensure_column
from agent_storage.task_event_bytes_schema import BYTE_BOUND, initialize_event_byte_bounds
from agent_storage.task_event_positions_schema import POSITION_SCHEMA


def initialize_task_positions(connection: sqlite3.Connection) -> None:
    ensure_column(connection, "session_events", "task_id", "TEXT")
    ensure_column(
        connection, "session_events", "task_sequence", "INTEGER CHECK(task_sequence >= 0)"
    )
    ensure_column(connection, "agent_tasks", "next_event_sequence", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(
        connection, "agent_tasks", "event_position_state", "TEXT NOT NULL DEFAULT 'legacy'"
    )
    ensure_column(connection, "agent_tasks", "event_position_cursor", "INTEGER NOT NULL DEFAULT -1")
    ensure_column(
        connection, "agent_tasks", "event_index_repair_cursor", "INTEGER NOT NULL DEFAULT -1"
    )
    ensure_column(
        connection, "agent_tasks", "event_index_repair_highwater", "INTEGER NOT NULL DEFAULT -1"
    )
    ensure_column(
        connection,
        "execution_segments",
        "event_position_source_cursor",
        "INTEGER NOT NULL DEFAULT -1",
    )
    ensure_column(
        connection,
        "execution_segments",
        "event_position_source_ready",
        "INTEGER NOT NULL DEFAULT 0",
    )
    connection.executescript(POSITION_SCHEMA)
    initialize_event_byte_bounds(connection)


def backfill_task_event_positions(
    connection: sqlite3.Connection,
    task_id: TaskId,
    *,
    limit: int = 256,
) -> bool:
    """One shared metadata budget; progress survives the caller's commit."""
    if not 1 <= limit <= 256:
        raise ValueError("Task position backfill limit must be between 1 and 256")
    key = str(task_id)
    task = connection.execute(
        """SELECT next_event_sequence,event_position_state,event_position_cursor
           FROM agent_tasks WHERE task_id=?""",
        (key,),
    ).fetchone()
    if task is None:
        raise ValueError("Task position backfill target was not found")
    phase, cursor, next_sequence = str(task[1]), int(task[2]), int(task[0])
    if phase == "legacy":
        next_sequence = connection.execute(
            """SELECT MAX(COALESCE((SELECT MAX(task_sequence)
                            FROM session_events WHERE task_id=?),-1),
                          COALESCE((SELECT MAX(task_sequence)
                            FROM task_event_index WHERE task_id=?),-1))+1""",
            (key, key),
        ).fetchone()[0]
        phase = "validating"
    if phase == "validating":
        rows = _position_rows(connection, key, cursor, limit)
        for row in rows:
            if row["task_sequence"] != cursor + 1 or (
                row["member_task"],
                row["session_id"],
                row["sequence"],
            ) != (key, row["segment_id"], row["segment_sequence"]):
                raise ValueError("legacy Task reservation is ambiguous")
            _assign(connection, key, row, row["task_sequence"])
            cursor = row["task_sequence"]
        limit -= len(rows)
        if not _position_rows(connection, key, cursor, 1):
            phase = "assigning"
    if phase == "ready" and _pending_segment(connection, key) is not None:
        phase = "assigning"
    connection.execute(
        "UPDATE agent_tasks SET event_position_state=? WHERE task_id=?", (phase, key)
    )
    while phase == "assigning" and limit:
        member = _pending_segment(connection, key)
        if member is None:
            phase = "ready"
            break
        rows = connection.execute(
            """SELECT event_id,session_id,sequence,task_id AS source_task,
                      task_sequence AS source_position
               FROM session_events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT ?""",
            (member["session_id"], member["event_position_source_cursor"], limit),
        ).fetchall()
        source_cursor = member["event_position_source_cursor"]
        for row in rows:
            position = next_sequence if row["source_task"] is None else row["source_position"]
            _assign(connection, key, row, position)
            next_sequence += int(row["source_task"] is None)
            source_cursor = row["sequence"]
        limit -= max(len(rows), 1)  # Empty Segments also consume bounded work.
        more = connection.execute(
            "SELECT 1 FROM session_events WHERE session_id=? AND sequence>? LIMIT 1",
            (member["session_id"], source_cursor),
        ).fetchone()
        connection.execute(
            """UPDATE execution_segments SET event_position_source_cursor=?,
                      event_position_source_ready=?
               WHERE session_id=?""",
            (source_cursor, int(more is None), member["session_id"]),
        )
        if _pending_segment(connection, key) is None:
            phase = "ready"
    connection.execute(
        """UPDATE agent_tasks SET next_event_sequence=?,event_position_state=?,
                  event_position_cursor=?
           WHERE task_id=?""",
        (next_sequence, phase, cursor, key),
    )
    if phase == "ready" and limit:
        repair_task_event_index(connection, task_id, limit=limit)
    return phase == "ready"


def _pending_segment(connection: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = connection.execute(
        """SELECT session_id,event_position_source_cursor FROM execution_segments
           WHERE task_id=? AND event_position_source_ready=0 ORDER BY segment_index LIMIT 1""",
        (key,),
    ).fetchone()
    return row


def _position_rows(
    connection: sqlite3.Connection,
    key: str,
    cursor: int,
    limit: int,
    *,
    highwater: int = 9_223_372_036_854_775_807,
) -> list[sqlite3.Row]:
    # Both input seeks are bounded before UNION; no mismatch-filtered history scan.
    return connection.execute(
        """WITH candidates AS (
             SELECT * FROM (SELECT task_sequence,event_id,segment_id,segment_sequence
               FROM task_event_index WHERE task_id=? AND task_sequence>? AND task_sequence<=?
               ORDER BY task_sequence LIMIT ?)
             UNION SELECT * FROM (SELECT task_sequence,event_id,session_id,sequence
               FROM session_events WHERE task_id=? AND task_sequence>? AND task_sequence<=?
               ORDER BY task_sequence LIMIT ?))
           SELECT candidate.*,event.session_id,event.sequence,event.task_id AS source_task,
                  event.task_sequence AS source_position,member.task_id AS member_task
           FROM candidates candidate LEFT JOIN session_events event
             ON event.event_id=candidate.event_id
           LEFT JOIN execution_segments member ON member.session_id=event.session_id
           ORDER BY candidate.task_sequence LIMIT ?""",
        (key, cursor, highwater, limit, key, cursor, highwater, limit, limit),
    ).fetchall()


def _assign(connection: sqlite3.Connection, key: str, row: sqlite3.Row, position: int) -> int:
    actual = row["source_task"], row["source_position"]
    if actual[0] is not None and actual[0] != key:
        raise ValueError("source Event belongs to another Task")
    if actual != (None, None) and actual != (key, position):
        raise ValueError("legacy Task reservation conflicts with source")
    if row["sequence"] > 0:
        previous = connection.execute(
            "SELECT task_id,task_sequence FROM session_events WHERE session_id=? AND sequence=?",
            (row["session_id"], row["sequence"] - 1),
        ).fetchone()
        if previous is None or previous[0] is None:
            raise ValueError("legacy Task reservation omits a source prefix")
        if previous[0] != key:
            raise ValueError("source Event belongs to another Task")
        if previous[1] >= position:
            raise ValueError("legacy Task reservations invert source order")
    if actual == (None, None):
        connection.execute(
            """UPDATE session_events SET task_id=?,task_sequence=?
               WHERE event_id=? AND task_id IS NULL""",
            (key, position, row["event_id"]),
        )
    connection.execute(
        f"UPDATE session_events SET event_bytes_bound={BYTE_BOUND} WHERE event_id=?",
        (row["event_id"],),
    )
    mapped = connection.execute(
        """SELECT task_id,task_sequence,segment_id,segment_sequence
           FROM task_event_index WHERE event_id=?""",
        (row["event_id"],),
    ).fetchone()
    if mapped is not None:
        if tuple(mapped) != (key, position, row["session_id"], row["sequence"]):
            raise ValueError("derived Task position conflicts with source")
        return 0
    connection.execute(
        """INSERT INTO task_event_index
             (task_id,task_sequence,event_id,segment_id,segment_sequence)
           VALUES (?,?,?,?,?)""",
        (key, position, row["event_id"], row["session_id"], row["sequence"]),
    )
    return 1


def repair_task_event_index(
    connection: sqlite3.Connection, task_id: TaskId, *, limit: int = 256
) -> int:
    if not 1 <= limit <= 256:
        raise ValueError("Task index repair limit must be between 1 and 256")
    key = str(task_id)
    task = connection.execute(
        """SELECT event_index_repair_cursor,next_event_sequence,event_index_repair_highwater
           FROM agent_tasks WHERE task_id=?""",
        (key,),
    ).fetchone()
    if task is None:
        raise ValueError("Task index repair target was not found")
    cursor, repaired = task[0], 0
    highwater = task[1] - 1 if task[2] == -1 else task[2]
    if cursor > highwater or highwater >= task[1]:
        raise ValueError("canonical Task repair checkpoint conflicts with source")
    if _position_rows(connection, key, task[1] - 1, 1):
        raise ValueError("derived Task position conflicts with source highwater")
    for row in _position_rows(connection, key, cursor, limit, highwater=highwater):
        if row["member_task"] != key or (row["source_task"], row["source_position"]) != (
            key,
            row["task_sequence"],
        ):
            raise ValueError("derived Task position conflicts with source")
        if row["task_sequence"] != cursor + 1 or row["task_sequence"] >= task[1]:
            raise ValueError("canonical Task source coverage is incomplete")
        repaired += _assign(connection, key, row, row["task_sequence"])
        cursor = row["task_sequence"]
    if not _position_rows(connection, key, cursor, 1, highwater=highwater):
        if cursor != highwater:
            raise ValueError("canonical Task source coverage is incomplete")
        cursor = -1
        highwater = -1
    connection.execute(
        """UPDATE agent_tasks SET event_index_repair_cursor=?,event_index_repair_highwater=?
           WHERE task_id=?""",
        (cursor, highwater, key),
    )
    return repaired
