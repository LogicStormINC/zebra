"""SQLite derived Task summaries and metadata-first attachment seek pages."""

import sqlite3
from time import monotonic
from typing import cast
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_read_summaries import TaskAttachmentPage, TaskReadSummary

from agent_storage.database import SQLiteDatabase
from agent_storage.task_event_pages import read_task_event_page
from agent_storage.task_read_summary_rows import (
    admit_attachment_rows,
    advance_turn_page,
    attachment_from_row,
    derive_page,
    page_request,
    summary_from_row,
    turn_state,
    usage_state,
    validate_attachment_sources,
)


def _scope(connection: sqlite3.Connection, task_id: TaskId) -> sqlite3.Row | None:
    if not isinstance(task_id, UUID):
        raise ValueError("invalid Task summary identity")
    row = connection.execute(
        "SELECT namespace,next_event_sequence,event_position_state,active_segment_id "
        "FROM agent_tasks "
        "WHERE task_id=?",
        (str(task_id),),
    ).fetchone()
    if row is not None and row["event_position_state"] != "ready":
        raise CheckpointNotReady("Task summary source positions require explicit repair")
    return cast(sqlite3.Row | None, row)


def _head(connection: sqlite3.Connection, namespace: str, task_id: TaskId) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        connection.execute(
            "SELECT * FROM task_read_summary_heads WHERE deployment_namespace=? AND task_id=?",
            (namespace, str(task_id)),
        ).fetchone(),
    )


def _frontier(
    connection: sqlite3.Connection,
    namespace: str,
    task_id: TaskId,
    through: int,
) -> tuple[int, int]:
    if through == -1:
        return 0, 0
    row = connection.execute(
        "SELECT f.attachment_count,f.attachment_bytes,f.event_id,f.segment_id,f.segment_sequence,"
        "e.task_id,e.task_sequence,e.session_id,e.sequence,m.task_id AS member_task,"
        "m.event_position_source_ready,m.event_position_source_cursor "
        "FROM task_read_summary_frontiers f LEFT JOIN session_events e ON e.event_id=f.event_id "
        "LEFT JOIN execution_segments m ON m.session_id=e.session_id "
        "WHERE f.deployment_namespace=? AND f.task_id=? AND f.task_sequence=?",
        (namespace, str(task_id), through),
    ).fetchone()
    if row is None or (
        row["task_id"],
        row["task_sequence"],
        row["session_id"],
        row["sequence"],
        row["member_task"],
    ) != (str(task_id), through, row["segment_id"], row["segment_sequence"], str(task_id)):
        raise CheckpointConflict("Task summary frontier conflicts with canonical source")
    if not row["event_position_source_ready"]:
        raise CheckpointNotReady("Task summary Segment requires explicit repair")
    if row["sequence"] > row["event_position_source_cursor"]:
        raise CheckpointConflict("Task summary frontier exceeds canonical Segment coverage")
    return row["attachment_count"], row["attachment_bytes"]


def _validate_head(
    connection: sqlite3.Connection,
    task_id: TaskId,
    task: sqlite3.Row,
    head: sqlite3.Row | None,
) -> TaskReadSummary:
    summary = summary_from_row(
        task_id, task["next_event_sequence"] - 1, head, task["active_segment_id"]
    )
    counts = _frontier(connection, task["namespace"], task_id, summary.through_sequence)
    if counts != (summary.attachment_count, summary.attachment_bytes):
        raise CheckpointConflict("Task summary counters conflict with persisted frontier")
    return summary


class SQLiteTaskReadSummaryMixin:
    _database: SQLiteDatabase

    def read_task_summary(self, task_id: TaskId) -> TaskReadSummary | None:
        with self._database.connect() as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            task = _scope(connection, task_id)
            if task is None:
                return None
            return _validate_head(
                connection, task_id, task, _head(connection, task["namespace"], task_id)
            )

    def read_attachment_page(
        self,
        task_id: TaskId,
        after_ordinal: int = -1,
        *,
        through_sequence: int | None = None,
        limit: int = 256,
        max_bytes: int = 1_048_576,
    ) -> TaskAttachmentPage:
        page_request(after_ordinal, limit, max_bytes, through_sequence)
        with self._database.connect() as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            task = _scope(connection, task_id)
            if task is None:
                raise ValueError("Task attachment target was not found")
            namespace, key = task["namespace"], str(task_id)
            summary = _validate_head(
                connection, task_id, task, _head(connection, namespace, task_id)
            )
            through = summary.highwater if through_sequence is None else through_sequence
            if through > summary.highwater:
                raise ValueError("attachment window exceeds canonical highwater")
            if through > summary.through_sequence:
                raise CheckpointNotReady("Task attachment summary requires explicit repair")
            count, size = _frontier(connection, namespace, task_id, through)
            if after_ordinal >= count:
                raise ValueError("attachment cursor exceeds captured coverage")
            metadata = connection.execute(
                "SELECT a.ordinal,a.ref_bytes,a.task_sequence,f.segment_id,f.segment_sequence,"
                "e.task_id AS source_task,e.task_sequence AS source_position,e.session_id,"
                "e.sequence AS source_sequence,e.event_type,m.task_id AS member_task,"
                "m.event_position_source_ready,m.event_position_source_cursor "
                "FROM task_attachment_index a LEFT JOIN task_read_summary_frontiers f "
                "ON f.deployment_namespace=a.deployment_namespace AND f.task_id=a.task_id "
                "AND f.task_sequence=a.task_sequence "
                "LEFT JOIN session_events e ON e.event_id=f.event_id "
                "LEFT JOIN execution_segments m ON m.session_id=e.session_id "
                "WHERE a.deployment_namespace=? AND a.task_id=? AND a.ordinal>=? AND a.ordinal<? "
                "ORDER BY a.ordinal LIMIT ?",
                (namespace, key, max(0, after_ordinal), count, limit + int(after_ordinal >= 0)),
            ).fetchall()
            validate_attachment_sources(metadata, task_id, through)
            if after_ordinal >= 0:
                if not metadata or metadata[0]["ordinal"] != after_ordinal:
                    raise CheckpointConflict("attachment cursor has missing canonical coverage")
                metadata = metadata[1:]
            admitted, byte_count = admit_attachment_rows(
                metadata,
                after_ordinal,
                count,
                max_bytes,
                limit=limit,
            )
            rows = (
                connection.execute(
                    "SELECT a.ordinal,a.task_sequence,a.ref_json,a.ref_bytes,f.event_id "
                    "FROM task_attachment_index a JOIN task_read_summary_frontiers f "
                    "ON f.deployment_namespace=a.deployment_namespace AND f.task_id=a.task_id "
                    "AND f.task_sequence=a.task_sequence "
                    "WHERE a.deployment_namespace=? AND a.task_id=? "
                    "AND a.ordinal>? AND a.ordinal<=? ORDER BY a.ordinal LIMIT ?",
                    (namespace, key, after_ordinal, after_ordinal + admitted, admitted),
                ).fetchall()
                if admitted
                else []
            )
            if len(rows) != admitted:
                raise CheckpointConflict("indexed attachment page changed or lost coverage")
            return TaskAttachmentPage(
                task_id,
                through,
                after_ordinal,
                count,
                size,
                tuple(attachment_from_row(row) for row in rows),
                byte_count,
            )

    def backfill_read_summary(
        self,
        task_id: TaskId,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
    ) -> bool:
        page_request(-1, limit, max_bytes, None)
        deadline = monotonic() + 2
        with self._database.connect() as connection:
            connection.execute("PRAGMA busy_timeout=2000")
            connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
            connection.execute("BEGIN IMMEDIATE")
            task = _scope(connection, task_id)
            if task is None:
                raise ValueError("Task summary target was not found")
            namespace, key = task["namespace"], str(task_id)
            connection.execute(
                "INSERT OR IGNORE INTO task_read_summary_heads(deployment_namespace,task_id) "
                "VALUES (?,?)",
                (namespace, key),
            )
            head = _head(connection, namespace, task_id)
            assert head is not None
            summary = _validate_head(connection, task_id, task, head)
            state = usage_state(head["usage_state_json"])
            turn_through = turn_state(state, summary.through_sequence)["through_sequence"]
            if turn_through < summary.through_sequence:
                page = read_task_event_page(
                    connection,
                    task_id,
                    turn_through,
                    limit=limit,
                    max_bytes=max_bytes,
                    through=summary.through_sequence,
                )
                changed = connection.execute(
                    "UPDATE task_read_summary_heads SET usage_state_json=? "
                    "WHERE deployment_namespace=? AND task_id=? AND through_sequence=?",
                    (advance_turn_page(state, page), namespace, key, summary.through_sequence),
                )
                if changed.rowcount != 1:
                    raise CheckpointConflict("Turn summary frontier changed during preparation")
                return False
            page = read_task_event_page(
                connection,
                task_id,
                summary.through_sequence,
                limit=limit,
                max_bytes=max_bytes,
                through=summary.highwater,
            )
            derived = derive_page(page, head)
            for row in derived.frontiers:
                connection.execute(
                    "INSERT INTO task_read_summary_frontiers VALUES (?,?,?,?,?,?,?,?)",
                    (namespace, key, *row),
                )
            for row in derived.attachments:
                connection.execute(
                    "INSERT INTO task_attachment_index VALUES (?,?,?,?,?,?,?)",
                    (namespace, key, *row),
                )
            if monotonic() >= deadline:
                raise TimeoutError("Task summary derivation deadline exceeded")
            changed = connection.execute(
                "UPDATE task_read_summary_heads SET through_sequence=?,usage_state_json=?,"
                "attachment_count=?,attachment_bytes=? WHERE deployment_namespace=? AND task_id=? "
                "AND through_sequence=?",
                (
                    page.next_sequence,
                    derived.usage_json,
                    derived.count,
                    derived.size,
                    namespace,
                    key,
                    summary.through_sequence,
                ),
            )
            if changed.rowcount != 1:
                raise CheckpointConflict("Task summary frontier changed during derivation")
            return not page.has_more
