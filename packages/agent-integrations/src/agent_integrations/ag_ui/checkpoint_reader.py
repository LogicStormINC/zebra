"""Bounded checkpoint Page cache; no source body hydration."""

from agent_core.domain.identifiers import SessionId
from agent_core.ports.stream_source_head import StreamCheckpointReadPort
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_BYTES,
    MAX_CHECKPOINT_KEYS,
    CheckpointConflict,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionScope,
    SegmentCheckpoint,
)

from agent_integrations.ag_ui.contracts import AgUiProjectionError


class ProjectionPageBudgetExceeded(AgUiProjectionError):
    """A smaller source prefix may fit; never a reason to retry source validation."""


class _PageReader:
    def __init__(
        self,
        port: StreamCheckpointReadPort,
        scope: ProjectionScope,
        before: int,
        *,
        budget_error: type[AgUiProjectionError] = AgUiProjectionError,
    ) -> None:
        self.port, self.scope, self.before = port, scope, before
        self.budget_error = budget_error
        self.header_budget = 0
        self.cells: dict[ProjectionCellKey, ProjectionCell | None] = {}
        self.scalars: dict[SessionId, SegmentCheckpoint] = {}
        self.changes: list[ProjectionCell] = []

    def _check_buffer(self) -> None:
        size = (
            512
            + self.header_budget
            + len(self.scalars) * 128
            + sum(
                256
                + 6 * len(key.key.encode())
                + 6 * len((row.value if row is not None and row.value is not None else "").encode())
                for key, row in self.cells.items()
            )
            + sum(
                256 + 6 * len(row.key.key.encode()) + 6 * len((row.value or "").encode())
                for row in self.changes
            )
        )
        if size > MAX_CHECKPOINT_BYTES:
            raise self.budget_error("checkpoint Page buffer exceeds byte bound")

    def reserve_header(self) -> None:
        self.header_budget += 384  # Core transition's conservative header + scalar record budget.
        self._check_buffer()

    def load(self, keys: tuple[ProjectionCellKey, ...]) -> tuple[ProjectionCell, ...]:
        missing = tuple(dict.fromkeys(key for key in keys if key not in self.cells))
        if len(self.cells) + len(missing) > MAX_CHECKPOINT_KEYS:
            raise self.budget_error("checkpoint Page exceeds keyed-state bound")
        if missing:
            rows = self.port.read_cells_at(self.scope, self.before, missing)
            if len(rows) > len(missing):
                raise CheckpointConflict("checkpoint returned excess keyed rows")
            found: set[ProjectionCellKey] = set()
            size = 0
            for row in rows:
                if row.key not in missing or row.key in found or row.task_sequence >= self.before:
                    raise CheckpointConflict("checkpoint returned foreign/future cell")
                found.add(row.key)
                size += 128 + len(row.key.key.encode()) + len((row.value or "").encode())
                self.cells[row.key] = row
            if size > MAX_CHECKPOINT_BYTES:
                raise AgUiProjectionError("checkpoint cell read exceeds byte bound")
            self.cells.update((key, None) for key in missing if key not in found)
            self._check_buffer()
        return tuple(cached for key in keys if (cached := self.cells[key]) is not None)

    def scalar(self, segment: SessionId) -> SegmentCheckpoint:
        if segment not in self.scalars:
            scalar = self.port.read_segment_checkpoint_before(self.scope, segment, self.before)
            if scalar.segment_id != segment or scalar.task_sequence >= self.before:
                raise CheckpointConflict("checkpoint returned foreign/future scalar")
            self.scalars[segment] = scalar
        return self.scalars[segment]

    def change(self, key: ProjectionCellKey, position: int, value: str | None) -> None:
        rows = self.load((key,))
        if (rows[0].value if rows else None) == value:
            return
        if len(self.changes) >= MAX_CHECKPOINT_KEYS:
            raise self.budget_error("checkpoint Page exceeds cell-transition bound")
        row = ProjectionCell(key, position, value)
        self.cells[key] = row
        self.changes.append(row)
        self._check_buffer()
