"""Derived-only Task checkpoint Port; short transactions lock only their head."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic
from typing import cast

from agent_core.domain.identifiers import SessionId
from agent_core.ports.stream_source_head import StreamCheckpointReadPort
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_BYTES,
    CellKind,
    CheckpointConflict,
    CheckpointStale,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)
from psycopg import errors

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline
from agent_storage.postgres.task_projection_checkpoint_rows import (
    FRAME_COLUMNS,
    SCOPE_WHERE,
    Connection,
    frame_at,
    head_at,
    require_scope,
    require_segments,
    scalar_before,
    scope_values,
    validate_transition,
)
from agent_storage.task_projection_checkpoint_rows import cell_bytes, read_position, validate_keys


class PostgresTaskProjectionCheckpointMixin:
    _database: PostgresDatabase

    def _check_namespace(self, scope: ProjectionScope) -> None:
        if scope.namespace != self._database.deployment_namespace:
            raise CheckpointConflict("checkpoint namespace does not match this Store")

    def _head(self, connection: Connection, scope: ProjectionScope) -> ProjectionCheckpointHead:
        self._check_namespace(scope)
        return head_at(connection, scope)

    def read_checkpoint_head(self, scope: ProjectionScope) -> ProjectionCheckpointHead:
        self._check_namespace(scope)
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return self._head(connection, scope)

    def read_event_projection_header(
        self,
        scope: ProjectionScope,
        task_sequence: int,
    ) -> ProjectionFrameHeader | None:
        self._check_namespace(scope)
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            read_position(self._head(connection, scope), task_sequence)
            return frame_at(connection, scope, task_sequence)

    def read_segment_checkpoint_before(
        self,
        scope: ProjectionScope,
        segment_id: SessionId,
        before_sequence: int,
    ) -> SegmentCheckpoint:
        self._check_namespace(scope)
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            read_position(self._head(connection, scope), before_sequence, before=True)
            require_segments(connection, scope, (segment_id,))
            return scalar_before(connection, scope, segment_id, before_sequence)

    def read_cells_at(
        self,
        scope: ProjectionScope,
        before_sequence: int,
        keys: tuple[ProjectionCellKey, ...],
    ) -> tuple[ProjectionCell, ...]:
        self._check_namespace(scope)
        validate_keys(keys)  # Bound SQL/request bytes before opening a connection.
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            read_position(self._head(connection, scope), before_sequence, before=True)
            return _cells_at(connection, scope, before_sequence, keys)

    @contextmanager
    def read_checkpoint_snapshot(
        self, scope: ProjectionScope, position: int
    ) -> Iterator[StreamCheckpointReadPort]:
        self._check_namespace(scope)
        with task_io_deadline(monotonic() + 2), self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            head = self._head(connection, scope)
            read_position(head, position)
            reader = _EventCheckpointRead(connection, head, position)
            try:
                yield reader
            finally:
                reader.closed = True

    def commit_projection_page(self, transition: ProjectionTransition) -> ProjectionCheckpointHead:
        self._check_namespace(transition.scope)
        scope, values = transition.scope, scope_values(transition.scope)
        try:
            with self._database.connect_task_io() as connection:
                next_sequence = require_scope(connection, scope)
                # Native first-head race: the loser waits for the same derived
                # head, then loses CAS. No source/Task/Session lock or DML.
                connection.execute(
                    """INSERT INTO task_projection_heads
                       (deployment_namespace,task_id,anchor_key,projector_version)
                       VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    values,
                )
                locked = connection.execute(
                    f"""SELECT through_sequence FROM task_projection_heads
                        WHERE {SCOPE_WHERE} FOR UPDATE""",
                    values,
                ).fetchone()
                if locked is not None and locked["through_sequence"] > transition.expected_through:
                    raise CheckpointStale("checkpoint frontier CAS advanced before commit")
                if locked is None or locked["through_sequence"] != transition.expected_through:
                    raise CheckpointConflict("checkpoint frontier lost CAS")
                head = self._head(connection, scope)
                validate_transition(connection, transition, next_sequence)
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO task_projection_frames
                           (deployment_namespace,task_id,anchor_key,projector_version,"""
                        + FRAME_COLUMNS
                        + ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [
                            (
                                *values,
                                h.task_sequence,
                                h.event_id,
                                h.segment_id,
                                h.segment_sequence,
                                h.state_before_sequence,
                                h.frame_count,
                                h.projected,
                                h.eligible,
                            )
                            for h in transition.headers
                        ],
                    )
                    cursor.executemany(
                        """INSERT INTO task_projection_scalars
                           (deployment_namespace,task_id,anchor_key,projector_version,segment_id,
                            task_sequence,segment_sequence,started,turn_finished)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        [
                            (
                                *values,
                                s.segment_id,
                                s.task_sequence,
                                s.segment_sequence,
                                s.started,
                                s.turn_finished,
                            )
                            for s in transition.scalars
                        ],
                    )
                    cursor.executemany(
                        """INSERT INTO task_projection_cells
                           (deployment_namespace,task_id,anchor_key,projector_version,segment_id,
                            cell_kind,cell_key,task_sequence,value,byte_count)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        [
                            (
                                *values,
                                c.key.segment_id,
                                c.key.kind,
                                c.key.key,
                                c.task_sequence,
                                c.value,
                                cell_bytes(c.key, c.value),
                            )
                            for c in transition.cells
                        ],
                    )
                latest = next(
                    (h for h in reversed(transition.headers) if h.eligible), head.latest_eligible
                )
                terminal = transition.terminal_sequence
                if terminal is None and head.terminal is not None:
                    terminal = head.terminal.task_sequence
                updated = connection.execute(
                    f"""UPDATE task_projection_heads SET through_sequence=%s,last_event_id=%s,
                           latest_eligible_sequence=%s,terminal_sequence=%s
                        WHERE {SCOPE_WHERE} AND through_sequence=%s""",
                    (
                        transition.through_sequence,
                        transition.headers[-1].event_id,
                        latest.task_sequence if latest is not None else None,
                        terminal,
                        *values,
                        transition.expected_through,
                    ),
                )
                if updated.rowcount != 1:
                    raise CheckpointStale("checkpoint frontier lost CAS")
                return head_at(connection, scope)
        except errors.UniqueViolation as exc:
            raise CheckpointConflict("checkpoint Event/version already has derived state") from exc


def _cells_at(
    connection: Connection,
    scope: ProjectionScope,
    before_sequence: int,
    keys: tuple[ProjectionCellKey, ...],
) -> tuple[ProjectionCell, ...]:
    require_segments(connection, scope, tuple(key.segment_id for key in keys))
    if not keys:
        return ()
    metadata = connection.execute(
        f"""SELECT requested.segment_id,requested.cell_kind,requested.cell_key,
                   cell.task_sequence,cell.byte_count
            FROM unnest(%s::uuid[],%s::text[],%s::text[])
                requested(segment_id,cell_kind,cell_key)
            CROSS JOIN LATERAL (SELECT task_sequence,byte_count FROM task_projection_cells
              WHERE {SCOPE_WHERE} AND segment_id=requested.segment_id
                AND cell_kind=requested.cell_kind AND cell_key=requested.cell_key
                AND task_sequence<%s ORDER BY task_sequence DESC LIMIT 1) cell""",
        (
            [key.segment_id for key in keys],
            [key.kind for key in keys],
            [key.key for key in keys],
            *scope_values(scope),
            before_sequence,
        ),
    ).fetchall()
    if 512 + sum(row["byte_count"] for row in metadata) > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint cell read exceeds byte bound")
    if not metadata:
        return ()
    rows = connection.execute(
        f"""SELECT requested.segment_id,requested.cell_kind,requested.cell_key,
                   cell.task_sequence,cell.value
            FROM unnest(%s::uuid[],%s::text[],%s::text[],%s::bigint[],%s::bigint[])
                requested(segment_id,cell_kind,cell_key,task_sequence,byte_count)
            CROSS JOIN LATERAL (SELECT task_sequence,value FROM task_projection_cells
              WHERE {SCOPE_WHERE} AND segment_id=requested.segment_id
                AND cell_kind=requested.cell_kind AND cell_key=requested.cell_key
                AND task_sequence=requested.task_sequence
                AND byte_count=requested.byte_count LIMIT 1) cell""",
        (
            [row["segment_id"] for row in metadata],
            [row["cell_kind"] for row in metadata],
            [row["cell_key"] for row in metadata],
            [row["task_sequence"] for row in metadata],
            [row["byte_count"] for row in metadata],
            *scope_values(scope),
        ),
    ).fetchall()
    if len(rows) != len(metadata):
        raise CheckpointConflict("checkpoint cells changed during their admitted read")
    cells = tuple(
        ProjectionCell(
            ProjectionCellKey(
                SessionId(row["segment_id"]),
                cast(CellKind, row["cell_kind"]),
                row["cell_key"],
            ),
            row["task_sequence"],
            row["value"],
        )
        for row in rows
    )
    expected = {
        (row["segment_id"], row["cell_kind"], row["cell_key"], row["task_sequence"]): row[
            "byte_count"
        ]
        for row in metadata
    }
    if any(
        cell_bytes(cell.key, cell.value)
        != expected[(cell.key.segment_id, cell.key.kind, cell.key.key, cell.task_sequence)]
        for cell in cells
    ):
        raise CheckpointConflict("checkpoint cell metadata conflicts with value")
    return cells


class _EventCheckpointRead:
    def __init__(self, connection: Connection, head: ProjectionCheckpointHead, position: int):
        self.connection, self.head, self.position = connection, head, position
        self.closed = False
        self.deadline = current_task_io_deadline()
        self.frame = frame_at(connection, head.scope, position)

    def _check(self, scope: ProjectionScope, position: int | None = None) -> None:
        if (
            self.closed
            or scope != self.head.scope
            or (position is not None and (type(position) is not int or position != self.position))
        ):
            raise CheckpointConflict("checkpoint reader is closed or outside its exact Event")
        if self.deadline is not None and monotonic() >= self.deadline:
            raise TimeoutError("checkpoint Event read deadline exceeded")

    def read_checkpoint_head(self, scope: ProjectionScope) -> ProjectionCheckpointHead:
        self._check(scope)
        return self.head

    def read_event_projection_header(
        self, scope: ProjectionScope, task_sequence: int
    ) -> ProjectionFrameHeader | None:
        self._check(scope, task_sequence)
        read_position(self.head, task_sequence)
        return self.frame

    def read_segment_checkpoint_before(
        self, scope: ProjectionScope, segment_id: SessionId, before_sequence: int
    ) -> SegmentCheckpoint:
        self._check(scope, before_sequence)
        read_position(self.head, before_sequence, before=True)
        require_segments(self.connection, scope, (segment_id,))
        return scalar_before(self.connection, scope, segment_id, before_sequence)

    def read_cells_at(
        self, scope: ProjectionScope, before_sequence: int, keys: tuple[ProjectionCellKey, ...]
    ) -> tuple[ProjectionCell, ...]:
        self._check(scope, before_sequence)
        validate_keys(keys)
        read_position(self.head, before_sequence, before=True)
        return _cells_at(self.connection, scope, before_sequence, keys)
