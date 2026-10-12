"""Bounded, resumable adoption and repair of canonical Task Event coordinates."""

from typing import Any

from agent_core.domain.identifiers import TaskId
from psycopg import errors

from agent_storage.postgres.task_event_source_bounds_migration import BYTE_BOUND
from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError

POSITION_BATCH_LIMIT = 256


def _lock_task(
    connection: Any,
    namespace: str,
    task_id: TaskId,
    *,
    shared: bool = False,
) -> None:
    # Root Task IDs equal Session IDs. Session/lease seed 0 must stay independent.
    lock = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    connection.execute(
        f"SELECT {lock}(hashtextextended(%s,61))",
        (f"{namespace}:{task_id}",),
    ).fetchone()


def backfill_task_event_positions(
    connection: Any, namespace: str, task_id: TaskId, *, limit: int = POSITION_BATCH_LIMIT
) -> bool:
    """One shared metadata budget; progress survives the caller's commit."""
    if not 1 <= limit <= POSITION_BATCH_LIMIT:
        raise ValueError("Task position backfill limit must be between 1 and 256")
    _lock_task(connection, namespace, task_id)
    task = connection.execute(
        """SELECT next_event_sequence,event_position_state,event_position_cursor
           FROM agent_tasks WHERE deployment_namespace=%s AND task_id=%s""",
        (namespace, task_id),
    ).fetchone()
    if task is None:
        raise PostgresAgentTaskConflictError("Task position backfill target was not found")
    phase, cursor, next_sequence = (
        str(task["event_position_state"]),
        int(task["event_position_cursor"]),
        int(task["next_event_sequence"]),
    )
    if phase == "legacy":
        row = connection.execute(
            """SELECT GREATEST(
                COALESCE((SELECT task_sequence FROM session_events
                    WHERE deployment_namespace=%s AND task_id=%s
                    ORDER BY task_sequence DESC LIMIT 1),-1),
                COALESCE((SELECT task_sequence FROM task_event_index
                    WHERE deployment_namespace=%s AND task_id=%s
                    ORDER BY task_sequence DESC LIMIT 1),-1))+1 AS next_sequence""",
            (namespace, task_id, namespace, task_id),
        ).fetchone()
        next_sequence, phase = row["next_sequence"], "validating"
    # Freeze reservations before adoption. New Segment prefixes must not use the
    # ordinary ready-state allocator's next-counter assignment guard.
    connection.execute(
        """UPDATE agent_tasks SET event_position_state=%s
           WHERE deployment_namespace=%s AND task_id=%s""",
        (phase, namespace, task_id),
    )
    if phase == "validating":
        rows = _position_rows(connection, namespace, task_id, cursor, limit)
        for row in rows:
            if row["task_sequence"] != cursor + 1 or (
                row["member_task"],
                row["session_id"],
                row["sequence"],
            ) != (task_id, row["segment_id"], row["segment_sequence"]):
                raise PostgresAgentTaskConflictError("legacy Task reservation is ambiguous")
            _assign(connection, namespace, task_id, row, row["task_sequence"])
            cursor = row["task_sequence"]
        limit -= len(rows)
        if not _position_rows(connection, namespace, task_id, cursor, 1):
            phase = "assigning"
    if phase == "ready" and _pending_segment(connection, namespace, task_id) is not None:
        phase = "assigning"
    connection.execute(
        """UPDATE agent_tasks SET event_position_state=%s
           WHERE deployment_namespace=%s AND task_id=%s""",
        (phase, namespace, task_id),
    )
    while phase == "assigning" and limit:
        member = _pending_segment(connection, namespace, task_id)
        if member is None:
            phase = "ready"
            break
        rows = connection.execute(
            """SELECT event_id,session_id,sequence,task_id AS source_task,
                      task_sequence AS source_position FROM session_events
               WHERE deployment_namespace=%s AND session_id=%s AND sequence>%s
               ORDER BY sequence LIMIT %s""",
            (namespace, member["session_id"], member["event_position_source_cursor"], limit),
        ).fetchall()
        source_cursor = member["event_position_source_cursor"]
        for row in rows:
            if row["sequence"] != source_cursor + 1:
                raise PostgresAgentTaskConflictError("canonical Task source coverage is incomplete")
            position = next_sequence if row["source_task"] is None else row["source_position"]
            if row["source_task"] is not None and position >= next_sequence:
                raise PostgresAgentTaskConflictError("source Event position exceeds Task counter")
            _assign(connection, namespace, task_id, row, position)
            next_sequence += int(row["source_task"] is None)
            source_cursor = row["sequence"]
        limit -= max(len(rows), 1)  # Empty Segments also consume bounded work.
        more = connection.execute(
            """SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND sequence>%s LIMIT 1""",
            (namespace, member["session_id"], source_cursor),
        ).fetchone()
        connection.execute(
            """UPDATE execution_segments SET event_position_source_cursor=%s,
                      event_position_source_ready=%s
               WHERE deployment_namespace=%s AND session_id=%s""",
            (source_cursor, more is None, namespace, member["session_id"]),
        )
        if _pending_segment(connection, namespace, task_id) is None:
            phase = "ready"
    connection.execute(
        """UPDATE agent_tasks SET next_event_sequence=%s,event_position_state=%s,
                  event_position_cursor=%s WHERE deployment_namespace=%s AND task_id=%s""",
        (next_sequence, phase, cursor, namespace, task_id),
    )
    if phase == "ready" and limit:
        repair_task_event_index(connection, namespace, task_id, limit=limit)
    return phase == "ready"


def _pending_segment(connection: Any, namespace: str, task_id: TaskId) -> Any:
    return connection.execute(
        """SELECT session_id,event_position_source_cursor FROM execution_segments
           WHERE deployment_namespace=%s AND task_id=%s AND NOT event_position_source_ready
           ORDER BY segment_index LIMIT 1""",
        (namespace, task_id),
    ).fetchone()


def _position_rows(
    connection: Any,
    namespace: str,
    task_id: TaskId,
    cursor: int,
    limit: int,
    *,
    highwater: int = 9_223_372_036_854_775_807,
    repair: bool = False,
) -> list[Any]:
    # Both indexed input seeks are bounded BEFORE UNION; never filter mismatches
    # over the history. No Event body or aggregate root count is loaded.
    proof_fields = (
        """,previous.task_id AS previous_task,
        previous.task_sequence AS previous_position,mapped.task_id AS mapped_task,
        mapped.task_sequence AS mapped_position,mapped.segment_id AS mapped_segment,
        mapped.segment_sequence AS mapped_sequence"""
        if repair
        else ""
    )
    proof_joins = (
        """LEFT JOIN LATERAL (
          SELECT task_id,task_sequence FROM session_events WHERE deployment_namespace=%s
            AND session_id=event.session_id AND sequence>=event.sequence-1
            AND sequence<event.sequence ORDER BY sequence DESC LIMIT 1
        ) previous ON true LEFT JOIN LATERAL (
          SELECT task_id,task_sequence,segment_id,segment_sequence FROM task_event_index
          WHERE deployment_namespace=%s AND event_id=candidate.event_id LIMIT 1
        ) mapped ON true"""
        if repair
        else ""
    )
    rows = connection.execute(
        f"""WITH candidates AS (
             (SELECT task_sequence,event_id,segment_id,segment_sequence FROM task_event_index
               WHERE deployment_namespace=%s AND task_id=%s
                 AND task_sequence>%s AND task_sequence<=%s ORDER BY task_sequence LIMIT %s)
             UNION
             (SELECT task_sequence,event_id,session_id,sequence FROM session_events
               WHERE deployment_namespace=%s AND task_id=%s
                 AND task_sequence>%s AND task_sequence<=%s ORDER BY task_sequence LIMIT %s))
           SELECT candidate.*,event.session_id,event.sequence,event.task_id AS source_task,
                  event.task_sequence AS source_position,member.task_id AS member_task
                  {proof_fields}
           FROM candidates candidate LEFT JOIN LATERAL (
             SELECT session_id,sequence,task_id,task_sequence FROM session_events
             WHERE deployment_namespace=%s AND event_id=candidate.event_id LIMIT 1
           ) event ON true LEFT JOIN LATERAL (
             SELECT task_id FROM execution_segments WHERE deployment_namespace=%s
               AND session_id=event.session_id LIMIT 1
           ) member ON true
           {proof_joins} ORDER BY candidate.task_sequence LIMIT %s""",
        (
            namespace,
            task_id,
            cursor,
            highwater,
            limit,
            namespace,
            task_id,
            cursor,
            highwater,
            limit,
            namespace,
            namespace,
            *((namespace, namespace) if repair else ()),
            limit,
        ),
    ).fetchall()
    return list(rows)


def _assign(connection: Any, namespace: str, task_id: TaskId, row: Any, position: int) -> int:
    actual = row["source_task"], row["source_position"]
    if actual[0] is not None and actual[0] != task_id:
        raise PostgresAgentTaskConflictError("source Event belongs to another Task")
    if actual != (None, None) and actual != (task_id, position):
        raise PostgresAgentTaskConflictError("legacy Task reservation conflicts with source")
    if row["sequence"] > 0:
        previous = connection.execute(
            """SELECT task_id,task_sequence FROM session_events
               WHERE deployment_namespace=%s AND session_id=%s AND sequence=%s""",
            (namespace, row["session_id"], row["sequence"] - 1),
        ).fetchone()
        if previous is None or previous["task_id"] is None:
            raise PostgresAgentTaskConflictError("legacy Task reservation omits a source prefix")
        if previous["task_id"] != task_id:
            raise PostgresAgentTaskConflictError("source Event belongs to another Task")
        if previous["task_sequence"] >= position:
            raise PostgresAgentTaskConflictError("legacy Task reservations invert source order")
    if actual == (None, None):
        connection.execute(
            """UPDATE session_events SET task_id=%s,task_sequence=%s
               WHERE deployment_namespace=%s AND event_id=%s AND task_id IS NULL""",
            (task_id, position, namespace, row["event_id"]),
        )
    connection.execute(
        f"UPDATE session_events SET event_bytes_bound={BYTE_BOUND} "
        f"WHERE deployment_namespace=%s AND event_id=%s AND event_bytes_bound "
        f"IS DISTINCT FROM ({BYTE_BOUND})",
        (namespace, row["event_id"]),
    )
    mapped = connection.execute(
        """SELECT task_id,task_sequence,segment_id,segment_sequence FROM task_event_index
           WHERE deployment_namespace=%s AND event_id=%s""",
        (namespace, row["event_id"]),
    ).fetchone()
    if mapped is not None:
        if (
            mapped["task_id"],
            mapped["task_sequence"],
            mapped["segment_id"],
            mapped["segment_sequence"],
        ) != (task_id, position, row["session_id"], row["sequence"]):
            raise PostgresAgentTaskConflictError("derived Task position conflicts with source")
        return 0
    try:
        connection.execute(
            """INSERT INTO task_event_index
               (deployment_namespace,task_id,task_sequence,event_id,segment_id,segment_sequence)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (namespace, task_id, position, row["event_id"], row["session_id"], row["sequence"]),
        )
    except errors.UniqueViolation as exc:
        raise PostgresAgentTaskConflictError("derived Task position conflicts with source") from exc
    return 1


def repair_task_event_index(
    connection: Any, namespace: str, task_id: TaskId, *, limit: int = POSITION_BATCH_LIMIT
) -> int:
    if not 1 <= limit <= POSITION_BATCH_LIMIT:
        raise ValueError("Task index repair limit must be between 1 and 256")
    _lock_task(connection, namespace, task_id)
    task = connection.execute(
        """SELECT event_index_repair_cursor,event_index_repair_highwater,next_event_sequence,
                  event_position_state FROM agent_tasks
           WHERE deployment_namespace=%s AND task_id=%s""",
        (namespace, task_id),
    ).fetchone()
    if task is None or task["event_position_state"] != "ready":
        raise PostgresAgentTaskConflictError("Task index repair requires ready source positions")
    cursor, repaired = task["event_index_repair_cursor"], 0
    highwater = (
        task["next_event_sequence"] - 1
        if task["event_index_repair_highwater"] == -1
        else task["event_index_repair_highwater"]
    )
    if cursor > highwater or highwater >= task["next_event_sequence"]:
        raise PostgresAgentTaskConflictError(
            "canonical Task repair checkpoint conflicts with source"
        )
    if _position_rows(connection, namespace, task_id, task["next_event_sequence"] - 1, 1):
        raise PostgresAgentTaskConflictError(
            "derived Task position conflicts with source highwater"
        )
    rows = _position_rows(
        connection,
        namespace,
        task_id,
        cursor,
        limit,
        highwater=highwater,
        repair=True,
    )
    missing = []
    for row in rows:
        if (
            row["member_task"],
            row["source_task"],
            row["source_position"],
            row["session_id"],
            row["sequence"],
        ) != (task_id, task_id, row["task_sequence"], row["segment_id"], row["segment_sequence"]):
            raise PostgresAgentTaskConflictError("derived Task position conflicts with source")
        if row["task_sequence"] != cursor + 1:
            raise PostgresAgentTaskConflictError("canonical Task source coverage is incomplete")
        if row["sequence"] > 0:
            if row["previous_task"] is None:
                raise PostgresAgentTaskConflictError(
                    "legacy Task reservation omits a source prefix"
                )
            if row["previous_task"] != task_id:
                raise PostgresAgentTaskConflictError("source Event belongs to another Task")
            if row["previous_position"] >= row["task_sequence"]:
                raise PostgresAgentTaskConflictError("legacy Task reservations invert source order")
        if row["mapped_task"] is None:
            missing.append(row["event_id"])
        elif (
            row["mapped_task"],
            row["mapped_position"],
            row["mapped_segment"],
            row["mapped_sequence"],
        ) != (task_id, row["task_sequence"], row["session_id"], row["sequence"]):
            raise PostgresAgentTaskConflictError("derived Task position conflicts with source")
        cursor = row["task_sequence"]
    # Validate the complete bounded page before DML. Native guards still arbitrate
    # conflicts; unchanged bounds must not mutate sealed MODEL source witnesses.
    if rows:
        connection.execute(
            f"UPDATE session_events SET event_bytes_bound={BYTE_BOUND} "
            f"WHERE deployment_namespace=%s AND event_id=ANY(%s) AND event_bytes_bound "
            f"IS DISTINCT FROM ({BYTE_BOUND})",
            (namespace, [row["event_id"] for row in rows]),
        )
    if missing:
        try:
            inserted = connection.execute(
                """INSERT INTO task_event_index
                   (deployment_namespace,task_id,task_sequence,event_id,segment_id,segment_sequence)
                   SELECT deployment_namespace,task_id,task_sequence,event_id,session_id,sequence
                   FROM session_events WHERE deployment_namespace=%s AND task_id=%s
                     AND event_id=ANY(%s) ORDER BY task_sequence""",
                (namespace, task_id, missing),
            )
        except errors.UniqueViolation as exc:
            raise PostgresAgentTaskConflictError(
                "derived Task position conflicts with source"
            ) from exc
        repaired = inserted.rowcount
        if repaired != len(missing):
            raise PostgresAgentTaskConflictError("canonical Task source coverage is incomplete")
    if not _position_rows(connection, namespace, task_id, cursor, 1, highwater=highwater):
        if cursor != highwater:
            raise PostgresAgentTaskConflictError("canonical Task source coverage is incomplete")
        cursor = highwater = -1
    connection.execute(
        """UPDATE agent_tasks SET event_index_repair_cursor=%s,event_index_repair_highwater=%s
           WHERE deployment_namespace=%s AND task_id=%s""",
        (cursor, highwater, namespace, task_id),
    )
    return repaired
