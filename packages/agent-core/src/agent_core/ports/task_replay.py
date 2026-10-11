"""Body-free canonical coordinates used before replay response headers."""

from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.domain.sessions import SessionStatus


@dataclass(frozen=True, slots=True)
class TaskReadHeader:
    """Scalar Task coordinates, without Segment membership or historical bodies."""

    task_id: TaskId
    active_segment_id: SessionId
    current_sequence: int
    title: str | None = None
    status: SessionStatus | None = None
    active_segment_sequence: int | None = None
    title_truncated: bool = False
    clarification_id: str | None = None
    clarification_invalid: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.task_id, UUID)
            or not isinstance(self.active_segment_id, UUID)
            or type(self.current_sequence) is not int
            or self.current_sequence < -1
        ):
            raise ValueError("invalid Task read header")
        if self.title is not None and (not isinstance(self.title, str) or len(self.title) > 512):
            raise ValueError("invalid observation title")
        if self.status is not None and not isinstance(self.status, SessionStatus):
            raise ValueError("invalid observation status")
        if self.active_segment_sequence is not None and (
            type(self.active_segment_sequence) is not int or self.active_segment_sequence < 0
        ):
            raise ValueError("invalid observation revision")
        if type(self.title_truncated) is not bool or type(self.clarification_invalid) is not bool:
            raise ValueError("invalid observation bounds")
        if self.clarification_id is not None and (
            not isinstance(self.clarification_id, str)
            or not self.clarification_id.strip()
            or len(self.clarification_id) > 256
            or any(ord(char) < 32 for char in self.clarification_id)
        ):
            raise ValueError("invalid observation clarification identity")


@dataclass(frozen=True, slots=True)
class TaskEventHeader:
    task_id: TaskId
    task_sequence: int
    event_id: EventId
    segment_id: SessionId
    segment_sequence: int
    event_type: EventType
    command_kind: str | None = None
    command_run_id: str | None = None
    internal_continuation: bool = False

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.task_sequence, self.segment_sequence)
        ):
            raise ValueError("invalid canonical Event header coordinates")
        if type(self.internal_continuation) is not bool:
            raise ValueError("invalid canonical continuation header")


@dataclass(frozen=True, slots=True)
class TaskRunHeader:
    task_id: TaskId
    run_id: str
    highwater: int
    anchor: TaskEventHeader | None
    start: int
    stop: int | None
    legacy: bool = False
    control_only: bool = False
    # Source-owned, Task-wide presence at this captured highwater, including
    # malformed TASK_PREPARED coverage_admission markers and coverage Events.
    strict_coverage: bool = False

    def __post_init__(self) -> None:
        if type(self.strict_coverage) is not bool:
            raise ValueError("invalid canonical Run coverage privacy")
        if not isinstance(self.run_id, str) or not self.run_id or len(self.run_id) > 256:
            raise ValueError("invalid replay Run identity")
        if type(self.highwater) is not int or self.highwater < -1:
            raise ValueError("invalid canonical Run highwater")
        if type(self.start) is not int or self.start < 0:
            raise ValueError("invalid canonical Run start")
        if self.anchor is not None and (
            self.anchor.task_id != self.task_id
            or self.anchor.task_sequence != self.start
            or self.start > self.highwater
            or self.anchor.command_run_id != self.run_id
            or self.anchor.internal_continuation
        ):
            raise ValueError("canonical Run anchor conflicts with source")
        if self.stop is not None and (
            type(self.stop) is not int or not self.start < self.stop <= self.highwater
        ):
            raise ValueError("invalid canonical Run stop")
        if self.legacy and (self.anchor is not None or self.start != 0 or self.stop is not None):
            raise ValueError("legacy Run cannot have a command anchor")


@dataclass(frozen=True, slots=True)
class TaskProjectionBlock:
    """One maximal contiguous Segment block, clipped to a captured highwater."""

    task_id: TaskId
    segment_id: SessionId
    first_task_sequence: int
    last_task_sequence: int
    first_segment_sequence: int
    last_segment_sequence: int
    previous_block_start: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID) or not isinstance(self.segment_id, UUID):
            raise ValueError("invalid projection block identity")
        coordinates = (
            self.first_task_sequence,
            self.last_task_sequence,
            self.first_segment_sequence,
            self.last_segment_sequence,
        )
        if any(type(n) is not int or not 0 <= n <= 2**63 - 1 for n in coordinates) or (
            self.first_task_sequence > self.last_task_sequence
            or self.first_segment_sequence > self.last_segment_sequence
            or self.last_task_sequence - self.first_task_sequence
            != self.last_segment_sequence - self.first_segment_sequence
        ):
            raise ValueError("invalid contiguous projection block range")
        previous = self.previous_block_start
        if previous is not None and (
            type(previous) is not int or not 0 <= previous < self.first_task_sequence
        ):
            raise ValueError("invalid same-Segment block predecessor")
        if (previous is None) != (self.first_segment_sequence == 0):
            raise ValueError("projection block omits its Segment predecessor")


@dataclass(frozen=True, slots=True)
class TaskHandoffHeader:
    """Frozen source metadata, not execution or cross-Task authority."""

    source: TaskEventHeader
    handoff_id: UUID
    peer_segment_id: SessionId

    def __post_init__(self) -> None:
        if (
            not isinstance(self.handoff_id, UUID)
            or not isinstance(self.peer_segment_id, UUID)
            or self.peer_segment_id == self.source.segment_id
            or self.source.event_type
            not in {
                EventType.SESSION_HANDOFF_COMMITTED,
                EventType.SESSION_HANDOFF_RECEIVED,
            }
        ):
            raise ValueError("invalid canonical handoff metadata")
