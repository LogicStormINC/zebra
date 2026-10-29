"""Bounded, derived Task projection state; canonical Events remain authority.

No method adopts Events, grants execution authority, or reads historical bodies.
Adapters namespace every query and atomically publish headers, cells and scalars
with the frontier CAS. Missing/not-ready state is an error, never hydration.
"""

from dataclasses import dataclass
from re import fullmatch
from typing import Literal, Protocol
from uuid import UUID

from agent_core.domain.identifiers import EventId, SessionId, TaskId

MAX_CHECKPOINT_EVENTS = 256
MAX_CHECKPOINT_KEYS = 1_024
MAX_CHECKPOINT_BYTES = 1_048_576
MAX_EVENT_FRAMES = 4_096
CellKind = Literal[
    "text_message",
    "text_ended",
    "tool_call",
    "interrupt",
    "run_member",
    "handoff",
    "coverage",
    "standard_v1",
]
CELL_KINDS = frozenset(
    {
        "text_message",
        "text_ended",
        "tool_call",
        "interrupt",
        "run_member",
        "handoff",
        "coverage",
        "standard_v1",
    }
)


def _text(value: str, name: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"invalid checkpoint {name}")


def _position(value: int, *, minimum: int = -1) -> None:
    if type(value) is not int or not minimum <= value <= 9_223_372_036_854_775_807:
        raise ValueError("invalid checkpoint position")


@dataclass(frozen=True, slots=True)
class ProjectionScope:
    namespace: str
    task_id: TaskId
    anchor_event_id: EventId | None
    projector_version: str

    def __post_init__(self) -> None:
        _text(self.namespace, "namespace", 256)
        _text(self.projector_version, "version", 64)
        if not isinstance(self.task_id, UUID) or (
            self.anchor_event_id is not None and not isinstance(self.anchor_event_id, UUID)
        ):
            raise ValueError("invalid checkpoint scope identity")


@dataclass(frozen=True, slots=True)
class ProjectionCellKey:
    segment_id: SessionId
    kind: CellKind
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, UUID) or self.kind not in CELL_KINDS:
            raise ValueError("invalid checkpoint cell kind or Segment")
        _text(self.key, "cell key", 1_024)


@dataclass(frozen=True, slots=True)
class ProjectionCell:
    key: ProjectionCellKey
    task_sequence: int
    value: str | None

    def __post_init__(self) -> None:
        _position(self.task_sequence, minimum=0)
        if self.value is not None:
            _text(self.value, "cell value", 2_048)
        if self.key.kind not in {
            "text_message",
            "handoff",
            "coverage",
            "standard_v1",
        } and self.value not in {None, "1"}:
            raise ValueError("membership cell must be 1 or a tombstone")


@dataclass(frozen=True, slots=True)
class SegmentCheckpoint:
    segment_id: SessionId
    task_sequence: int
    segment_sequence: int
    started: bool
    turn_finished: bool

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, UUID):
            raise ValueError("invalid checkpoint Segment")
        _position(self.task_sequence)
        _position(self.segment_sequence)
        if (self.task_sequence == -1) != (self.segment_sequence == -1):
            raise ValueError("initial checkpoint coordinates disagree")
        if type(self.started) is not bool or type(self.turn_finished) is not bool:
            raise ValueError("invalid checkpoint scalar flags")
        if self.task_sequence == -1 and (self.started or self.turn_finished):
            raise ValueError("initial checkpoint cannot have projected state")


@dataclass(frozen=True, slots=True)
class ProjectionFrameHeader:
    task_sequence: int
    event_id: EventId
    segment_id: SessionId
    segment_sequence: int
    state_before_sequence: int
    frame_count: int
    projected: bool
    eligible: bool

    def __post_init__(self) -> None:
        _position(self.task_sequence, minimum=0)
        _position(self.segment_sequence, minimum=0)
        _position(self.state_before_sequence)
        if not isinstance(self.event_id, UUID) or not isinstance(self.segment_id, UUID):
            raise ValueError("invalid checkpoint Event identity")
        if self.state_before_sequence >= self.task_sequence:
            raise ValueError("checkpoint must strictly precede its Event")
        if type(self.frame_count) is not int or not 0 <= self.frame_count <= MAX_EVENT_FRAMES:
            raise ValueError("checkpoint frame count exceeds its bound")
        if type(self.projected) is not bool or type(self.eligible) is not bool:
            raise ValueError("invalid checkpoint projection flags")
        if (self.eligible and not self.projected) or (not self.projected and self.frame_count):
            raise ValueError("ineligible/unprojected checkpoint frames disagree")


@dataclass(frozen=True, slots=True)
class ProjectionCheckpointHead:
    scope: ProjectionScope
    through_sequence: int = -1
    last_event_id: EventId | None = None
    latest_eligible: ProjectionFrameHeader | None = None
    terminal: ProjectionFrameHeader | None = None

    def __post_init__(self) -> None:
        _position(self.through_sequence)
        if (self.through_sequence == -1) != (self.last_event_id is None):
            raise ValueError("checkpoint frontier identity disagrees")
        if self.last_event_id is not None and not isinstance(self.last_event_id, UUID):
            raise ValueError("invalid checkpoint frontier Event")
        for header in (self.latest_eligible, self.terminal):
            if header is not None and (
                not header.eligible or header.task_sequence > self.through_sequence
            ):
                raise ValueError("checkpoint frontier contains a future/ineligible header")
        if self.terminal is not None and not self.terminal.frame_count:
            raise ValueError("checkpoint terminal must identify a public frame")


@dataclass(frozen=True, slots=True)
class ProjectionTransition:
    scope: ProjectionScope
    expected_through: int
    headers: tuple[ProjectionFrameHeader, ...]
    scalars: tuple[SegmentCheckpoint, ...]
    cells: tuple[ProjectionCell, ...]
    terminal_sequence: int | None = None

    def __post_init__(self) -> None:
        _position(self.expected_through)
        if any(type(rows) is not tuple for rows in (self.headers, self.scalars, self.cells)):
            raise ValueError("checkpoint transition collections must be immutable tuples")
        if not 1 <= len(self.headers) <= MAX_CHECKPOINT_EVENTS:
            raise ValueError("checkpoint transition exceeds Event bound")
        by_position = {header.task_sequence: header for header in self.headers}
        if tuple(by_position) != tuple(
            range(self.expected_through + 1, self.expected_through + 1 + len(self.headers))
        ) or len(by_position) != len(self.headers):
            raise ValueError("checkpoint transition has a position gap")
        if len({h.event_id for h in self.headers}) != len(self.headers):
            raise ValueError("checkpoint transition repeats an Event")
        scalar_positions = set()
        for scalar in self.scalars:
            header = by_position.get(scalar.task_sequence)
            if (
                header is None
                or not header.projected
                or (
                    scalar.segment_id != header.segment_id
                    or scalar.segment_sequence != header.segment_sequence
                    or scalar.task_sequence in scalar_positions
                )
            ):
                raise ValueError("checkpoint scalar conflicts with Event header")
            scalar_positions.add(scalar.task_sequence)
        if scalar_positions != {h.task_sequence for h in self.headers if h.projected}:
            raise ValueError("checkpoint transition omits projected scalar state")
        if len(self.cells) > MAX_CHECKPOINT_KEYS:
            raise ValueError("checkpoint transition exceeds cell bound")
        cell_positions = set()
        standard = (
            fullmatch(
                r"(?:agui-standard-1\.0|zebra-reliable-v2-agui-1\.0):r[1-9][0-9]{0,2}(?::coverage)?",
                self.scope.projector_version,
            )
            is not None
        )
        for cell in self.cells:
            if cell.key.kind == "standard_v1" and not standard:
                raise ValueError("standard cells require an explicit standard profile")
            header = by_position.get(cell.task_sequence)
            if (
                header is None
                or (cell.key.segment_id != header.segment_id and cell.key.kind != "standard_v1")
                or (cell.key, cell.task_sequence) in cell_positions
            ):
                raise ValueError("checkpoint cell conflicts with transition")
            if cell.key.kind not in {"run_member", "handoff"} and not header.projected:
                raise ValueError("projector state cell cannot mutate an unprojected Event")
            cell_positions.add((cell.key, cell.task_sequence))
        if self.terminal_sequence is not None:
            _position(self.terminal_sequence, minimum=0)
            header = by_position.get(self.terminal_sequence)
            if header is None or not header.eligible or not header.frame_count:
                raise ValueError("checkpoint terminal is not an eligible frame")
        if self.byte_count > MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint transition exceeds byte bound")

    @property
    def through_sequence(self) -> int:
        return self.headers[-1].task_sequence

    @property
    def byte_count(self) -> int:
        # Conservative typed-record budget; never serialize historical bodies.
        return (
            512
            + len(self.headers) * 256
            + len(self.scalars) * 128
            + sum(
                256
                + 6 * len(cell.key.key.encode("utf-8"))
                + (6 * len(cell.value.encode("utf-8")) if cell.value is not None else 0)
                for cell in self.cells
            )
        )


class TaskProjectionCheckpointPort(Protocol):
    """All reads are observational, scoped and indexed; no implicit backfill.

    read_cells_at returns at most one latest row (including tombstones) per
    requested key, strictly before before_sequence, with <=1024 keys and <=1MiB.
    An absent scalar returns the initial -1 scalar only within a ready frontier.
    A read beyond head.through_sequence + 1 raises CheckpointNotReady.
    commit_projection_page verifies canonical header identities, strict scalar
    predecessors and the exact expected frontier in one transaction. A lost CAS
    raises CheckpointConflict and publishes none of the page. Same Event/version
    conflicts must never overwrite previously published projection state.
    """

    def read_checkpoint_head(self, scope: ProjectionScope) -> ProjectionCheckpointHead: ...

    def read_event_projection_header(
        self,
        scope: ProjectionScope,
        task_sequence: int,
    ) -> ProjectionFrameHeader | None: ...

    def read_segment_checkpoint_before(
        self,
        scope: ProjectionScope,
        segment_id: SessionId,
        before_sequence: int,
    ) -> SegmentCheckpoint: ...

    def read_cells_at(
        self,
        scope: ProjectionScope,
        before_sequence: int,
        keys: tuple[ProjectionCellKey, ...],
    ) -> tuple[ProjectionCell, ...]: ...

    def commit_projection_page(
        self,
        transition: ProjectionTransition,
    ) -> ProjectionCheckpointHead: ...


class CheckpointNotReady(ValueError):
    """Explicit materialization/backfill is required; request must not hydrate."""


class CheckpointConflict(ValueError):
    """Lost CAS or derived/source identity conflict; no partial publication."""


class CheckpointStale(CheckpointConflict):
    """Another writer advanced the same frontier; retry observation, not execution."""
