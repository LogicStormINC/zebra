"""Indexed, scoped checkpoint reads composed on the existing SQLite Task Store."""

import sqlite3
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_BYTES,
    CheckpointConflict,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)

from agent_storage.database import SQLiteDatabase
from agent_storage.task_projection_checkpoint_commit import commit_page
from agent_storage.task_projection_checkpoint_rows import (
    SCOPE_WHERE,
    cell_bytes,
    frame_at,
    head_at,
    read_position,
    require_segments,
    scalar_before,
    scope_values,
    validate_keys,
)


class SQLiteTaskProjectionCheckpointMixin:
    _database: SQLiteDatabase

    def read_checkpoint_head(self, scope: ProjectionScope) -> ProjectionCheckpointHead:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            return head_at(connection, scope)

    def read_event_projection_header(
        self,
        scope: ProjectionScope,
        task_sequence: int,
    ) -> ProjectionFrameHeader | None:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            read_position(head_at(connection, scope), task_sequence)
            return frame_at(connection, scope, task_sequence)

    def read_segment_checkpoint_before(
        self,
        scope: ProjectionScope,
        segment_id: SessionId,
        before_sequence: int,
    ) -> SegmentCheckpoint:
        if not isinstance(segment_id, UUID):
            raise ValueError("invalid checkpoint Segment identity")
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            read_position(head_at(connection, scope), before_sequence, before=True)
            require_segments(connection, scope, (segment_id,))
            return scalar_before(connection, scope, segment_id, before_sequence)

    def read_cells_at(
        self,
        scope: ProjectionScope,
        before_sequence: int,
        keys: tuple[ProjectionCellKey, ...],
    ) -> tuple[ProjectionCell, ...]:
        validate_keys(keys)
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            read_position(head_at(connection, scope), before_sequence, before=True)
            require_segments(connection, scope, tuple(key.segment_id for key in keys))
            positions: list[tuple[ProjectionCellKey, int, int]] = []
            byte_count = 512
            for key in keys:
                row = connection.execute(
                    f"SELECT task_sequence,byte_count FROM task_projection_cells "
                    f"WHERE {SCOPE_WHERE} AND segment_id=? AND cell_kind=? AND cell_key=? "
                    "AND task_sequence<? ORDER BY task_sequence DESC LIMIT 1",
                    (*scope_values(scope), str(key.segment_id), key.kind, key.key, before_sequence),
                ).fetchone()
                if row is not None:
                    byte_count += row["byte_count"]
                    if byte_count > MAX_CHECKPOINT_BYTES:
                        raise ValueError("checkpoint cell read exceeds byte bound")
                    positions.append((key, row["task_sequence"], row["byte_count"]))
            cells = []
            for key, position, expected_bytes in positions:
                row = connection.execute(
                    f"SELECT value FROM task_projection_cells WHERE {SCOPE_WHERE} "
                    "AND segment_id=? AND cell_kind=? AND cell_key=? AND task_sequence=?",
                    (*scope_values(scope), str(key.segment_id), key.kind, key.key, position),
                ).fetchone()
                if row is None or cell_bytes(key, row["value"]) != expected_bytes:
                    raise CheckpointConflict("checkpoint cell metadata conflicts with value")
                cells.append(ProjectionCell(key, position, row["value"]))
            return tuple(cells)

    def commit_projection_page(
        self,
        transition: ProjectionTransition,
    ) -> ProjectionCheckpointHead:
        try:
            with self._database.connect() as connection:
                return commit_page(connection, transition)
        except sqlite3.IntegrityError as exc:
            raise CheckpointConflict("checkpoint page conflicts with published state") from exc
