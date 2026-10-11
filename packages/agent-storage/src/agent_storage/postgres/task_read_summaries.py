"""Native TaskIO-bounded PostgreSQL derived summaries and indexed attachment reads."""

from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_read_summaries import TaskAttachmentPage, TaskReadSummary

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_event_pages import read_task_event_page
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


def _scope(connection: Any, namespace: str, task_id: TaskId) -> Any:
    if not isinstance(task_id, UUID):
        raise ValueError("invalid Task summary identity")
    row = connection.execute(
        "SELECT next_event_sequence,event_position_state,active_segment_id FROM agent_tasks "
        "WHERE deployment_namespace=%s AND task_id=%s",
        (namespace, task_id),
    ).fetchone()
    if row is not None and row["event_position_state"] != "ready":
        raise CheckpointNotReady("Task summary source positions require explicit repair")
    return row


def _head(connection: Any, namespace: str, task_id: TaskId, *, lock: bool = False) -> Any:
    return connection.execute(
        "SELECT * FROM task_read_summary_heads WHERE deployment_namespace=%s AND task_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (namespace, task_id),
    ).fetchone()


def _frontier(connection: Any, namespace: str, task_id: TaskId, through: int) -> tuple[int, int]:
    if through == -1:
        return 0, 0
    row = connection.execute(
        "SELECT f.attachment_count,f.attachment_bytes,f.event_id,f.segment_id,f.segment_sequence,"
        "e.task_id,e.task_sequence,e.session_id,e.sequence,m.task_id AS member_task,"
        "m.event_position_source_ready,m.event_position_source_cursor "
        "FROM task_read_summary_frontiers f LEFT JOIN session_events e "
        "ON e.deployment_namespace=f.deployment_namespace AND e.event_id=f.event_id "
        "LEFT JOIN execution_segments m ON m.deployment_namespace=e.deployment_namespace "
        "AND m.session_id=e.session_id WHERE f.deployment_namespace=%s AND f.task_id=%s "
        "AND f.task_sequence=%s",
        (namespace, task_id, through),
    ).fetchone()
    if row is None or (
        row["task_id"],
        row["task_sequence"],
        row["session_id"],
        row["sequence"],
        row["member_task"],
    ) != (task_id, through, row["segment_id"], row["segment_sequence"], task_id):
        raise CheckpointConflict("Task summary frontier conflicts with canonical source")
    if not row["event_position_source_ready"]:
        raise CheckpointNotReady("Task summary Segment requires explicit repair")
    if row["sequence"] > row["event_position_source_cursor"]:
        raise CheckpointConflict("Task summary frontier exceeds canonical Segment coverage")
    return row["attachment_count"], row["attachment_bytes"]


def _validate_head(
    connection: Any, namespace: str, task_id: TaskId, task: Any, head: Any
) -> TaskReadSummary:
    summary = summary_from_row(
        task_id, task["next_event_sequence"] - 1, head, task["active_segment_id"]
    )
    if _frontier(connection, namespace, task_id, summary.through_sequence) != (
        summary.attachment_count,
        summary.attachment_bytes,
    ):
        raise CheckpointConflict("Task summary counters conflict with persisted frontier")
    return summary


class PostgresTaskReadSummaryMixin:
    _database: PostgresDatabase

    def read_task_summary(self, task_id: TaskId) -> TaskReadSummary | None:
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            namespace = self._database.deployment_namespace
            task = _scope(connection, namespace, task_id)
            if task is None:
                return None
            return _validate_head(
                connection, namespace, task_id, task, _head(connection, namespace, task_id)
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
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            namespace = self._database.deployment_namespace
            task = _scope(connection, namespace, task_id)
            if task is None:
                raise ValueError("Task attachment target was not found")
            summary = _validate_head(
                connection, namespace, task_id, task, _head(connection, namespace, task_id)
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
                "AND f.task_sequence=a.task_sequence LEFT JOIN session_events e "
                "ON e.deployment_namespace=f.deployment_namespace AND e.event_id=f.event_id "
                "LEFT JOIN execution_segments m ON m.deployment_namespace=e.deployment_namespace "
                "AND m.session_id=e.session_id WHERE a.deployment_namespace=%s AND a.task_id=%s "
                "AND a.ordinal>=%s AND a.ordinal<%s ORDER BY a.ordinal LIMIT %s",
                (namespace, task_id, max(0, after_ordinal), count, limit + int(after_ordinal >= 0)),
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
                    "WHERE a.deployment_namespace=%s AND a.task_id=%s "
                    "AND a.ordinal>%s AND a.ordinal<=%s ORDER BY a.ordinal LIMIT %s",
                    (namespace, task_id, after_ordinal, after_ordinal + admitted, admitted),
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
        """Rebuild old Turn-only prefixes in bounded pages, preserving usage/attachments.

        v3 includes exact cumulative human cardinality; compact v1/v2 records
        cannot initialize that counter and must replay from canonical position 0.
        """
        page_request(-1, limit, max_bytes, None)
        with self._database.connect_task_io() as connection:
            namespace = self._database.deployment_namespace
            if _scope(connection, namespace, task_id) is None:
                raise ValueError("Task summary target was not found")
            connection.execute(
                "INSERT INTO task_read_summary_heads(deployment_namespace,task_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING",
                (namespace, task_id),
            )
            head = _head(connection, namespace, task_id, lock=True)
            task = _scope(connection, namespace, task_id)
            summary = _validate_head(connection, namespace, task_id, task, head)
            state = usage_state(head["usage_state_json"])
            turn_through = turn_state(state, summary.through_sequence)["through_sequence"]
            if turn_through < summary.through_sequence:
                page = read_task_event_page(
                    connection,
                    namespace,
                    task_id,
                    turn_through,
                    limit=limit,
                    max_bytes=max_bytes,
                    through=summary.through_sequence,
                )
                changed = connection.execute(
                    "UPDATE task_read_summary_heads SET usage_state_json=%s "
                    "WHERE deployment_namespace=%s AND task_id=%s AND through_sequence=%s",
                    (advance_turn_page(state, page), namespace, task_id, summary.through_sequence),
                )
                if changed.rowcount != 1:
                    raise CheckpointConflict("Turn summary frontier changed during preparation")
                return False
            page = read_task_event_page(
                connection,
                namespace,
                task_id,
                summary.through_sequence,
                limit=limit,
                max_bytes=max_bytes,
                through=summary.highwater,
            )
            derived = derive_page(page, head)
            for row in derived.frontiers:
                position, event, segment, source_position, count, size = row
                connection.execute(
                    "INSERT INTO task_read_summary_frontiers VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        namespace,
                        task_id,
                        position,
                        UUID(str(event)),
                        UUID(str(segment)),
                        source_position,
                        count,
                        size,
                    ),
                )
            for row in derived.attachments:
                connection.execute(
                    "INSERT INTO task_attachment_index VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (namespace, task_id, *row),
                )
            changed = connection.execute(
                "UPDATE task_read_summary_heads SET through_sequence=%s,usage_state_json=%s,"
                "attachment_count=%s,attachment_bytes=%s "
                "WHERE deployment_namespace=%s AND task_id=%s "
                "AND through_sequence=%s",
                (
                    page.next_sequence,
                    derived.usage_json,
                    derived.count,
                    derived.size,
                    namespace,
                    task_id,
                    summary.through_sequence,
                ),
            )
            if changed.rowcount != 1:
                raise CheckpointConflict("Task summary frontier changed during derivation")
            return not page.has_more
