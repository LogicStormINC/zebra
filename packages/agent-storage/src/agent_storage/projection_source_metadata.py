"""SQLite indexed projection-source reads and explicitly bounded repair."""

import sqlite3
from typing import Any
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_replay import TaskEventHeader, TaskHandoffHeader, TaskProjectionBlock

from agent_storage.database import SQLiteDatabase
from agent_storage.projection_source_metadata_schema import BLOCK_COLUMNS, HEADER_COLUMNS


def position(value: int, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValueError("invalid projection metadata position")


def identity(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise ValueError("invalid projection metadata identity")


def handoff_header(row: Any) -> TaskHandoffHeader:
    if not row["projection_metadata_ready"] or row["projection_block_start"] is None:
        raise CheckpointNotReady("projection source metadata is not ready")
    try:
        return TaskHandoffHeader(
            TaskEventHeader(
                TaskId(UUID(str(row["task_id"]))),
                row["task_sequence"],
                EventId(UUID(str(row["event_id"]))),
                SessionId(UUID(str(row["session_id"]))),
                row["sequence"],
                EventType(row["event_type"]),
            ),
            UUID(str(row["projection_handoff_id"])),
            SessionId(UUID(str(row["projection_peer_segment_id"]))),
        )
    except (TypeError, ValueError) as exc:
        raise CheckpointConflict("invalid canonical handoff mapping") from exc


def projection_block(row: Any, task_id: TaskId, through: int) -> TaskProjectionBlock:
    end = min(row["last_task_sequence"], through)
    return TaskProjectionBlock(
        task_id,
        SessionId(UUID(str(row["segment_id"]))),
        row["first_task_sequence"],
        end,
        row["first_segment_sequence"],
        row["first_segment_sequence"] + end - row["first_task_sequence"],
        row["previous_block_start"],
    )


def _task(connection: sqlite3.Connection, task_id: TaskId, namespace: str | None = None) -> str:
    identity(task_id)
    task = connection.execute(
        "SELECT namespace,event_position_state FROM agent_tasks WHERE task_id=?", (str(task_id),)
    ).fetchone()
    if task is None or (namespace is not None and task["namespace"] != namespace):
        raise ValueError("projection metadata Task namespace is unavailable")
    if task["event_position_state"] != "ready":
        raise CheckpointNotReady("canonical Task positions require explicit backfill")
    return str(task["namespace"])


def _scope(connection: sqlite3.Connection, task_id: TaskId, through: int) -> str:
    position(through, -1)
    namespace = _task(connection, task_id)
    row = connection.execute(
        "SELECT next_event_sequence FROM agent_tasks WHERE task_id=?", (str(task_id),)
    ).fetchone()
    assert row is not None
    head = connection.execute(
        "SELECT through_sequence FROM task_projection_source_heads "
        "WHERE deployment_namespace=? AND task_id=?",
        (namespace, str(task_id)),
    ).fetchone()
    if through >= row["next_event_sequence"]:
        raise ValueError("projection metadata highwater exceeds canonical source")
    if (head is None and through >= 0) or (head is not None and through > head[0]):
        raise CheckpointNotReady(
            "projection source metadata is not ready; explicit backfill required"
        )
    if (
        connection.execute(
            "SELECT 1 FROM session_events INDEXED BY session_events_projection_pending "
            "WHERE task_id=? AND task_sequence<=? AND "
            "(projection_metadata_ready=0 OR projection_block_start IS NULL) LIMIT 1",
            (str(task_id), through),
        ).fetchone()
        is not None
    ):
        raise CheckpointNotReady("projection source metadata has missing coverage")
    return namespace


def _member(connection: sqlite3.Connection, task_id: TaskId, segment: SessionId) -> int:
    identity(segment)
    row = connection.execute(
        "SELECT task_id,event_position_source_ready,event_position_source_cursor "
        "FROM execution_segments WHERE session_id=?",
        (str(segment),),
    ).fetchone()
    if row is None or row["task_id"] != str(task_id):
        raise CheckpointConflict("projection source Segment belongs to another Task")
    if not row["event_position_source_ready"]:
        raise CheckpointNotReady("projection source Segment is not ready")
    return int(row["event_position_source_cursor"])


def _latest(
    connection: sqlite3.Connection, task_id: TaskId, segment: SessionId, handoff: UUID, before: int
) -> TaskHandoffHeader | None:
    identity(handoff)
    cursor = _member(connection, task_id, segment)
    row = connection.execute(
        f"SELECT {HEADER_COLUMNS} FROM session_events INDEXED BY session_events_projection_commit "
        "WHERE task_id=? AND session_id=? AND projection_handoff_id=? "
        "AND event_type='session_handoff_committed' AND task_sequence<? "
        "ORDER BY task_sequence DESC LIMIT 1",
        (str(task_id), str(segment), str(handoff), before),
    ).fetchone()
    if row is None:
        return None
    if row["sequence"] > cursor:
        raise CheckpointConflict("handoff commit conflicts with canonical source coverage")
    return handoff_header(row)


class SQLiteProjectionSourceMetadataMixin:
    _database: SQLiteDatabase

    def read_projection_block(
        self, task_id: TaskId, task_sequence: int, *, through_sequence: int
    ) -> TaskProjectionBlock:
        position(task_sequence)
        with self._database.connect() as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            namespace = _scope(connection, task_id, through_sequence)
            if task_sequence > through_sequence:
                raise ValueError("projection block is beyond captured highwater")
            source = connection.execute(
                f"SELECT {HEADER_COLUMNS} FROM session_events "
                "INDEXED BY session_events_projection_header "
                "WHERE task_id=? AND task_sequence=?",
                (str(task_id), task_sequence),
            ).fetchone()
            if source is None:
                raise CheckpointConflict("missing canonical projection block source")
            cursor = _member(connection, task_id, SessionId(UUID(source["session_id"])))
            row = connection.execute(
                f"SELECT {BLOCK_COLUMNS} FROM task_projection_blocks "
                "WHERE deployment_namespace=? AND task_id=? AND first_task_sequence=?",
                (namespace, str(task_id), source["projection_block_start"]),
            ).fetchone()
            if (
                row is None
                or row["segment_id"] != source["session_id"]
                or not (row["first_task_sequence"] <= task_sequence <= row["last_task_sequence"])
                or source["sequence"] > cursor
                or source["sequence"]
                != row["first_segment_sequence"] + task_sequence - row["first_task_sequence"]
            ):
                raise CheckpointConflict("projection block conflicts with canonical source")
            result = projection_block(row, task_id, through_sequence)
            if result.last_segment_sequence > cursor:
                raise CheckpointConflict("projection block exceeds canonical source coverage")
            canonical_end = connection.execute(
                "SELECT task_sequence FROM session_events "
                "INDEXED BY session_events_projection_block "
                "WHERE task_id=? AND projection_block_start=? AND task_sequence<=? "
                "ORDER BY task_sequence DESC LIMIT 1",
                (str(task_id), result.first_task_sequence, through_sequence),
            ).fetchone()
            if canonical_end is None or canonical_end[0] != result.last_task_sequence:
                raise CheckpointConflict("projection block range conflicts with source")
            for task_pos, segment_pos in (
                (result.first_task_sequence, result.first_segment_sequence),
                (result.last_task_sequence, result.last_segment_sequence),
            ):
                endpoint = connection.execute(
                    "SELECT session_id,sequence,projection_block_start FROM session_events "
                    "INDEXED BY session_events_projection_header "
                    "WHERE task_id=? AND task_sequence=?",
                    (str(task_id), task_pos),
                ).fetchone()
                if endpoint is None or tuple(endpoint) != (
                    str(result.segment_id),
                    segment_pos,
                    result.first_task_sequence,
                ):
                    raise CheckpointConflict(
                        "projection block boundaries conflict with canonical source"
                    )
            if result.previous_block_start is not None:
                predecessor = connection.execute(
                    "SELECT projection_block_start FROM session_events "
                    "WHERE session_id=? AND sequence=? AND task_id=?",
                    (str(result.segment_id), result.first_segment_sequence - 1, str(task_id)),
                ).fetchone()
                if predecessor is None or predecessor[0] != result.previous_block_start:
                    raise CheckpointConflict("same-Segment predecessor conflicts with source")
                previous = connection.execute(
                    f"SELECT {BLOCK_COLUMNS} FROM task_projection_blocks "
                    "WHERE deployment_namespace=? AND task_id=? AND first_task_sequence=?",
                    (namespace, str(task_id), result.previous_block_start),
                ).fetchone()
                if (
                    previous is None
                    or previous["segment_id"] != str(result.segment_id)
                    or (
                        previous["last_segment_sequence"] + 1 != result.first_segment_sequence
                        or previous["last_task_sequence"] >= result.first_task_sequence
                    )
                ):
                    raise CheckpointConflict(
                        "missing or conflicting same-Segment block predecessor"
                    )
            return result

    def read_handoff_receives(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        after_sequence: int = -1,
        *,
        through_sequence: int,
        limit: int = 256,
    ) -> tuple[TaskHandoffHeader, ...]:
        position(after_sequence, -1)
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("handoff seek limit must be between 1 and 256")
        with self._database.connect() as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            _scope(connection, task_id, through_sequence)
            cursor = _member(connection, task_id, segment_id)
            if after_sequence > through_sequence:
                raise ValueError("handoff seek exceeds captured highwater")
            rows = connection.execute(
                f"SELECT {HEADER_COLUMNS} FROM session_events "
                "INDEXED BY session_events_projection_receive "
                "WHERE task_id=? AND session_id=? AND task_sequence>? AND task_sequence<=? "
                "AND event_type='session_handoff_received' ORDER BY task_sequence LIMIT ?",
                (str(task_id), str(segment_id), after_sequence, through_sequence, limit),
            ).fetchall()
            result = []
            for row in rows:
                receive = handoff_header(row)
                duplicate = connection.execute(
                    "SELECT task_sequence FROM session_events "
                    "INDEXED BY session_events_projection_receive_identity "
                    "WHERE task_id=? AND session_id=? AND projection_handoff_id=? "
                    "AND event_type='session_handoff_received' AND task_sequence<=? "
                    "ORDER BY task_sequence LIMIT 2",
                    (str(task_id), str(segment_id), str(receive.handoff_id), through_sequence),
                ).fetchall()
                if len(duplicate) != 1 or row["sequence"] > cursor:
                    raise CheckpointConflict("ambiguous canonical handoff receive")
                result.append(receive)
            return tuple(result)

    def read_latest_handoff_commit(
        self,
        task_id: TaskId,
        source_segment_id: SessionId,
        handoff_id: UUID,
        before_sequence: int,
        *,
        through_sequence: int,
    ) -> TaskHandoffHeader | None:
        position(before_sequence)
        with self._database.connect() as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            _scope(connection, task_id, through_sequence)
            if before_sequence > through_sequence + 1:
                raise ValueError("handoff commit seek exceeds captured highwater")
            return _latest(connection, task_id, source_segment_id, handoff_id, before_sequence)


def write_projection_source_metadata(
    connection: sqlite3.Connection, namespace: str, event_id: EventId
) -> None:
    """Assignment hook is native; explicit retry/repair revalidates one source row."""
    identity(event_id)
    row = connection.execute(
        "SELECT e.task_id,t.namespace FROM session_events e "
        "JOIN agent_tasks t ON t.task_id=e.task_id JOIN execution_segments m "
        "ON m.session_id=e.session_id AND m.task_id=e.task_id WHERE e.event_id=?",
        (str(event_id),),
    ).fetchone()
    if row is None or row["namespace"] != namespace:
        raise ValueError("projection metadata source namespace/membership is unavailable")
    connection.execute(
        "UPDATE session_events SET task_id=task_id,task_sequence=task_sequence WHERE event_id=?",
        (str(event_id),),
    )
    source = connection.execute(
        "SELECT task_id,projection_block_start FROM session_events WHERE event_id=?",
        (str(event_id),),
    ).fetchone()
    assert source is not None
    start = source["projection_block_start"]
    if start is None:  # Import queues rows whose preceding page is not yet adopted.
        return
    extrema = [
        connection.execute(
            "SELECT task_sequence,session_id,sequence FROM session_events "
            "INDEXED BY session_events_projection_block "
            "WHERE task_id=? AND projection_block_start=? "
            f"ORDER BY task_sequence {direction} LIMIT 1",
            (source["task_id"], start),
        ).fetchone()
        for direction in ("ASC", "DESC")
    ]
    first, last = extrema
    assert first is not None and last is not None
    if first[0] != start or first[1] != last[1] or last[0] - first[0] != last[2] - first[2]:
        raise CheckpointConflict("projection block conflicts with source")
    predecessor = None
    if first[2] > 0:
        previous = connection.execute(
            "SELECT projection_block_start FROM session_events "
            "WHERE session_id=? AND sequence=? AND task_id=?",
            (first[1], first[2] - 1, source["task_id"]),
        ).fetchone()
        if previous is None or previous[0] is None or previous[0] >= start:
            raise CheckpointConflict("missing same-Segment block predecessor")
        predecessor = previous[0]
    expected = first[1], start, last[0], first[2], last[2], predecessor
    connection.execute(
        "INSERT OR IGNORE INTO task_projection_blocks"
        f"(deployment_namespace,task_id,{BLOCK_COLUMNS}) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (namespace, source["task_id"], *expected),
    )
    stored = connection.execute(
        f"SELECT {BLOCK_COLUMNS} FROM task_projection_blocks "
        "WHERE deployment_namespace=? AND task_id=? AND first_task_sequence=?",
        (namespace, source["task_id"], start),
    ).fetchone()
    if stored is None or tuple(stored) != expected:
        raise CheckpointConflict("projection block conflicts with source")


def backfill_projection_source_metadata(
    connection: sqlite3.Connection, namespace: str, task_id: TaskId, *, limit: int = 256
) -> bool:
    """Caller owns an IMMEDIATE transaction. Frozen repair cycles inspect <=limit headers."""
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("projection backfill limit must be between 1 and 256")
    _task(connection, task_id, namespace)
    connection.execute(
        "INSERT OR IGNORE INTO task_projection_source_heads"
        "(deployment_namespace,task_id) VALUES (?,?)",
        (namespace, str(task_id)),
    )
    connection.execute(
        "UPDATE task_projection_source_heads SET repair_highwater=(SELECT next_event_sequence-1 "
        "FROM agent_tasks WHERE task_id=?) WHERE deployment_namespace=? "
        "AND task_id=? AND repair_highwater=-1",
        (str(task_id), namespace, str(task_id)),
    )
    head = connection.execute(
        "SELECT repair_cursor,repair_highwater FROM task_projection_source_heads "
        "WHERE deployment_namespace=? AND task_id=?",
        (namespace, str(task_id)),
    ).fetchone()
    assert head is not None
    rows = connection.execute(
        f"SELECT {HEADER_COLUMNS} FROM session_events INDEXED BY session_events_projection_header "
        "WHERE task_id=? AND task_sequence>? AND task_sequence<=? ORDER BY task_sequence LIMIT ?",
        (str(task_id), head[0], head[1], limit),
    ).fetchall()
    cursor = int(head[0])
    for row in rows:
        if row["task_sequence"] != cursor + 1 or row["sequence"] > _member(
            connection, task_id, SessionId(UUID(row["session_id"]))
        ):
            raise CheckpointConflict("projection metadata source coverage conflicts")
        write_projection_source_metadata(connection, namespace, EventId(UUID(row["event_id"])))
        cursor = int(row["task_sequence"])
    if not rows and cursor < head[1]:
        raise CheckpointConflict("projection metadata source coverage is missing")
    done = cursor >= int(head[1])
    if done:
        current = connection.execute(
            "SELECT through_sequence FROM task_projection_source_heads "
            "WHERE deployment_namespace=? AND task_id=?",
            (namespace, str(task_id)),
        ).fetchone()
        if current is None or current[0] < head[1]:
            raise CheckpointNotReady("projection source metadata is not ready")
    connection.execute(
        "UPDATE task_projection_source_heads SET repair_cursor=?,repair_highwater=? "
        "WHERE deployment_namespace=? AND task_id=?",
        (-1 if done else cursor, -1 if done else head[1], namespace, str(task_id)),
    )
    return done
