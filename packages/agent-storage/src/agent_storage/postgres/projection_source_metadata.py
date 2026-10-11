"""Indexed PG projection-source reads and explicit bounded maintenance."""

from typing import Any
from uuid import UUID

import psycopg
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_replay import TaskHandoffHeader, TaskProjectionBlock

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.projection_source_metadata import (
    handoff_header,
    identity,
    position,
    projection_block,
)
from agent_storage.projection_source_metadata_schema import BLOCK_COLUMNS, HEADER_COLUMNS

Connection = psycopg.Connection[dict[str, Any]]


def _task(connection: Connection, namespace: str, task_id: TaskId) -> dict[str, Any]:
    identity(task_id)
    row = connection.execute(
        "SELECT next_event_sequence,event_position_state FROM agent_tasks "
        "WHERE deployment_namespace=%s AND task_id=%s",
        (namespace, task_id),
    ).fetchone()
    if row is None:
        raise ValueError("projection metadata Task namespace is unavailable")
    if row["event_position_state"] != "ready":
        raise CheckpointNotReady("canonical Task positions require explicit backfill")
    return row


def _scope(connection: Connection, namespace: str, task: TaskId, through: int) -> None:
    position(through, -1)
    row = _task(connection, namespace, task)
    if through >= row["next_event_sequence"]:
        raise ValueError("projection metadata highwater exceeds canonical source")
    head = connection.execute(
        "SELECT through_sequence FROM task_projection_source_heads "
        "WHERE deployment_namespace=%s AND task_id=%s",
        (namespace, task),
    ).fetchone()
    if (head is None and through >= 0) or (head is not None and through > head["through_sequence"]):
        raise CheckpointNotReady(
            "projection source metadata is not ready; explicit backfill required"
        )
    if (
        connection.execute(
            "SELECT 1 FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
            "AND task_sequence<=%s AND "
            "(NOT projection_metadata_ready OR projection_block_start IS NULL) LIMIT 1",
            (namespace, task, through),
        ).fetchone()
        is not None
    ):
        raise CheckpointNotReady("projection source metadata has missing coverage")


def _member(connection: Connection, namespace: str, task: TaskId, segment: SessionId) -> int:
    identity(segment)
    row = connection.execute(
        "SELECT task_id,event_position_source_ready,event_position_source_cursor "
        "FROM execution_segments WHERE deployment_namespace=%s AND session_id=%s",
        (namespace, segment),
    ).fetchone()
    if row is None or row["task_id"] != task:
        raise CheckpointConflict("projection source Segment belongs to another Task")
    if not row["event_position_source_ready"]:
        raise CheckpointNotReady("projection source Segment is not ready")
    return int(row["event_position_source_cursor"])


def _latest(
    connection: Connection,
    namespace: str,
    task: TaskId,
    segment: SessionId,
    handoff: UUID,
    before: int,
) -> TaskHandoffHeader | None:
    identity(handoff)
    cursor = _member(connection, namespace, task, segment)
    row = connection.execute(
        f"SELECT {HEADER_COLUMNS} FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
        "AND session_id=%s AND projection_handoff_id=%s AND event_type='session_handoff_committed' "
        "AND task_sequence<%s ORDER BY task_sequence DESC LIMIT 1",
        (namespace, task, segment, handoff, before),
    ).fetchone()
    if row is None:
        return None
    if row["sequence"] > cursor:
        raise CheckpointConflict("handoff commit conflicts with canonical source coverage")
    return handoff_header(row)


class PostgresProjectionSourceMetadataMixin:
    _database: PostgresDatabase

    def read_projection_block(
        self, task_id: TaskId, task_sequence: int, *, through_sequence: int
    ) -> TaskProjectionBlock:
        position(task_sequence)
        namespace = self._database.deployment_namespace
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            _scope(connection, namespace, task_id, through_sequence)
            if task_sequence > through_sequence:
                raise ValueError("projection block is beyond captured highwater")
            source = connection.execute(
                f"SELECT {HEADER_COLUMNS} FROM session_events "
                "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s",
                (namespace, task_id, task_sequence),
            ).fetchone()
            if source is None:
                raise CheckpointConflict("missing canonical projection block source")
            cursor = _member(connection, namespace, task_id, SessionId(source["session_id"]))
            row = connection.execute(
                f"SELECT {BLOCK_COLUMNS} FROM task_projection_blocks "
                "WHERE deployment_namespace=%s AND task_id=%s AND first_task_sequence=%s",
                (namespace, task_id, source["projection_block_start"]),
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
                "WHERE deployment_namespace=%s AND task_id=%s AND projection_block_start=%s "
                "AND task_sequence<=%s ORDER BY task_sequence DESC LIMIT 1",
                (namespace, task_id, result.first_task_sequence, through_sequence),
            ).fetchone()
            if canonical_end is None or canonical_end["task_sequence"] != result.last_task_sequence:
                raise CheckpointConflict("projection block range conflicts with source")
            for task_pos, segment_pos in (
                (result.first_task_sequence, result.first_segment_sequence),
                (result.last_task_sequence, result.last_segment_sequence),
            ):
                endpoint = connection.execute(
                    "SELECT session_id,sequence,projection_block_start FROM session_events "
                    "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s",
                    (namespace, task_id, task_pos),
                ).fetchone()
                if endpoint is None or tuple(endpoint.values()) != (
                    result.segment_id,
                    segment_pos,
                    result.first_task_sequence,
                ):
                    raise CheckpointConflict(
                        "projection block boundaries conflict with canonical source"
                    )
            if result.previous_block_start is not None:
                predecessor = connection.execute(
                    "SELECT projection_block_start FROM session_events "
                    "WHERE deployment_namespace=%s AND session_id=%s "
                    "AND sequence=%s AND task_id=%s",
                    (namespace, result.segment_id, result.first_segment_sequence - 1, task_id),
                ).fetchone()
                if (
                    predecessor is None
                    or predecessor["projection_block_start"] != result.previous_block_start
                ):
                    raise CheckpointConflict("same-Segment predecessor conflicts with source")
                previous = connection.execute(
                    f"SELECT {BLOCK_COLUMNS} FROM task_projection_blocks "
                    "WHERE deployment_namespace=%s AND task_id=%s AND first_task_sequence=%s",
                    (namespace, task_id, result.previous_block_start),
                ).fetchone()
                if (
                    previous is None
                    or previous["segment_id"] != result.segment_id
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
        namespace = self._database.deployment_namespace
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            _scope(connection, namespace, task_id, through_sequence)
            cursor = _member(connection, namespace, task_id, segment_id)
            if after_sequence > through_sequence:
                raise ValueError("handoff seek exceeds captured highwater")
            rows = connection.execute(
                f"SELECT {HEADER_COLUMNS} FROM session_events "
                "WHERE deployment_namespace=%s AND task_id=%s "
                "AND session_id=%s AND task_sequence>%s AND task_sequence<=%s "
                "AND event_type='session_handoff_received' ORDER BY task_sequence LIMIT %s",
                (namespace, task_id, segment_id, after_sequence, through_sequence, limit),
            ).fetchall()
            result = []
            for row in rows:
                receive = handoff_header(row)
                duplicates = connection.execute(
                    "SELECT task_sequence FROM session_events "
                    "WHERE deployment_namespace=%s AND task_id=%s "
                    "AND session_id=%s AND projection_handoff_id=%s "
                    "AND event_type='session_handoff_received' "
                    "AND task_sequence<=%s ORDER BY task_sequence LIMIT 2",
                    (namespace, task_id, segment_id, receive.handoff_id, through_sequence),
                ).fetchall()
                if len(duplicates) != 1 or row["sequence"] > cursor:
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
        namespace = self._database.deployment_namespace
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            _scope(connection, namespace, task_id, through_sequence)
            if before_sequence > through_sequence + 1:
                raise ValueError("handoff commit seek exceeds captured highwater")
            return _latest(
                connection, namespace, task_id, source_segment_id, handoff_id, before_sequence
            )


def write_projection_source_metadata(
    connection: Connection, namespace: str, event_id: EventId
) -> None:
    """Explicit one-row retry; native assignment invokes the same SQL function."""
    identity(event_id)
    if (
        connection.execute(
            "SELECT 1 FROM session_events e JOIN execution_segments m "
            "ON m.deployment_namespace=e.deployment_namespace "
            "AND m.session_id=e.session_id AND m.task_id=e.task_id JOIN agent_tasks t "
            "ON t.deployment_namespace=e.deployment_namespace AND t.task_id=e.task_id "
            "WHERE e.deployment_namespace=%s AND e.event_id=%s",
            (namespace, event_id),
        ).fetchone()
        is None
    ):
        raise ValueError("projection metadata source namespace/membership is unavailable")
    try:
        connection.execute("SELECT write_projection_source_metadata(%s,%s)", (namespace, event_id))
    except psycopg.errors.ObjectNotInPrerequisiteState as exc:
        raise CheckpointConflict(str(exc)) from exc


def backfill_projection_source_metadata(
    connection: Connection, namespace: str, task_id: TaskId, *, limit: int = 256
) -> bool:
    """Caller owns transaction; own derived head lock, fixed highwater, <=limit source headers."""
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("projection backfill limit must be between 1 and 256")
    task = _task(connection, namespace, task_id)
    head = connection.execute(
        "SELECT repair_cursor,repair_highwater FROM task_projection_source_heads "
        "WHERE deployment_namespace=%s AND task_id=%s",
        (namespace, task_id),
    ).fetchone()
    if head is None:
        head = {"repair_cursor": -1, "repair_highwater": -1}
    cursor = int(head["repair_cursor"])
    highwater = int(
        task["next_event_sequence"] - 1
        if head["repair_highwater"] == -1
        else head["repair_highwater"]
    )
    rows = connection.execute(
        f"SELECT {HEADER_COLUMNS} FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
        "AND task_sequence>%s AND task_sequence<=%s ORDER BY task_sequence LIMIT %s FOR UPDATE",
        (namespace, task_id, cursor, highwater, limit),
    ).fetchall()
    # Source rows first, own derived head last: assignment already holds source
    # UPDATE locks before calling the native builder. Never invert that order.
    connection.execute(
        "INSERT INTO task_projection_source_heads(deployment_namespace,task_id) "
        "VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (namespace, task_id),
    )
    locked = connection.execute(
        "SELECT repair_cursor,repair_highwater FROM task_projection_source_heads "
        "WHERE deployment_namespace=%s AND task_id=%s FOR UPDATE",
        (namespace, task_id),
    ).fetchone()
    if locked != head:
        raise CheckpointConflict("projection metadata repair frontier changed; retry transaction")
    for row in rows:
        if row["task_sequence"] != cursor + 1 or row["sequence"] > _member(
            connection, namespace, task_id, SessionId(row["session_id"])
        ):
            raise CheckpointConflict("projection metadata source coverage conflicts")
        write_projection_source_metadata(connection, namespace, EventId(row["event_id"]))
        cursor = int(row["task_sequence"])
    if not rows and cursor < highwater:
        raise CheckpointConflict("projection metadata source coverage is missing")
    done = cursor >= highwater
    if done:
        current = connection.execute(
            "SELECT through_sequence FROM task_projection_source_heads "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (namespace, task_id),
        ).fetchone()
        if current is None or current["through_sequence"] < highwater:
            raise CheckpointNotReady("projection source metadata is not ready")
    connection.execute(
        "UPDATE task_projection_source_heads SET repair_cursor=%s,repair_highwater=%s "
        "WHERE deployment_namespace=%s AND task_id=%s",
        (-1 if done else cursor, -1 if done else highwater, namespace, task_id),
    )
    return done
