from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agent_core.domain.agent_tasks import AgentTask, ExecutionSegment, RolloverReason
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.task_projection_checkpoints import TaskProjectionCheckpointPort
from agent_core.ports.task_read_summaries import TaskReadSummaryPort
from agent_core.ports.task_replay import (
    TaskEventHeader,
    TaskHandoffHeader,
    TaskProjectionBlock,
    TaskReadHeader,
    TaskRunHeader,
)
from agent_core.ports.worker_progress import WorkerProgressPort


@dataclass(frozen=True, slots=True)
class TaskEvent:
    task_id: TaskId
    task_sequence: int
    segment_id: SessionId
    segment_sequence: int
    event: SessionEvent


@dataclass(frozen=True, slots=True)
class TaskEventPage:
    """A bounded canonical suffix at one captured highwater, including silent Events."""

    events: tuple[TaskEvent, ...]
    after_sequence: int
    highwater: int
    byte_count: int

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not int
                for value in (
                    self.after_sequence,
                    self.highwater,
                    self.byte_count,
                )
            )
            or not -1 <= self.after_sequence <= self.highwater
        ):
            raise ValueError("invalid Task page coordinates")
        if len(self.events) > 256 or not 0 <= self.byte_count <= 1_048_576:
            raise ValueError("Task page exceeds its count or byte budget")
        for index, entry in enumerate(self.events, self.after_sequence + 1):
            if entry.task_sequence != index or index > self.highwater:
                raise ValueError("canonical Task page has a position gap")
            if entry.segment_id != entry.event.session_id or (
                entry.segment_sequence != entry.event.sequence
            ):
                raise ValueError("canonical Task page conflicts with source")
        if not self.events and self.after_sequence != self.highwater:
            raise ValueError("canonical Task page omits source coverage")

    @property
    def next_sequence(self) -> int:
        return self.events[-1].task_sequence if self.events else self.after_sequence

    @property
    def has_more(self) -> bool:
        return self.next_sequence < self.highwater


class AgentTaskPort(
    TaskProjectionCheckpointPort, WorkerProgressPort, TaskReadSummaryPort, Protocol
):
    def ensure_for_session(self, session_id: SessionId) -> AgentTask: ...

    def task_id_for_session(self, session_id: SessionId) -> TaskId | None:
        """Read only an existing indexed identity; never adopt or hydrate history."""
        ...

    def get_task(self, task_id: TaskId) -> AgentTask | None: ...

    def read_task_header(
        self, task_id: TaskId, *, require_source_coverage: bool = False
    ) -> TaskReadHeader | None:
        """Read indexed coordinates only; never adopt or hydrate historical bodies."""
        ...

    def list_tasks(self, *, limit: int) -> tuple[AgentTask, ...]: ...

    def segments(self, task_id: TaskId) -> tuple[ExecutionSegment, ...]: ...

    def segment_page(
        self, task_id: TaskId, *, after_index: int = -1, limit: int = 50
    ) -> tuple[ExecutionSegment, ...]: ...

    def active_segment(self, task_id: TaskId) -> SessionId | None: ...

    def attach_segment(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        *,
        predecessor_id: SessionId,
        reason: RolloverReason,
    ) -> AgentTask: ...

    def read_events(self, task_id: TaskId, after_sequence: int) -> tuple[TaskEvent, ...]: ...

    # Explicit maintenance only: callers must not repair from observational GETs.
    def backfill_event_positions(self, task_id: TaskId, *, limit: int = 256) -> bool: ...

    def backfill_replay_headers(
        self,
        task_id: TaskId,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        timeout_seconds: float = 2.0,
    ) -> bool: ...

    def backfill_projection_sources(self, task_id: TaskId, *, limit: int = 256) -> bool: ...

    def read_event_page(
        self,
        task_id: TaskId,
        after_sequence: int,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        through_sequence: int | None = None,
    ) -> TaskEventPage: ...

    def read_event_header(self, task_id: TaskId, task_sequence: int) -> TaskEventHeader | None: ...

    def read_run_header(
        self,
        task_id: TaskId,
        run_id: str,
        *,
        through_sequence: int | None = None,
    ) -> TaskRunHeader: ...

    def read_latest_run_header(self, task_id: TaskId) -> TaskRunHeader:
        """Seek the latest executable canonical Run; never infer its identity."""
        ...

    def read_projection_block(
        self,
        task_id: TaskId,
        task_sequence: int,
        *,
        through_sequence: int,
    ) -> TaskProjectionBlock: ...

    def read_handoff_receives(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        after_sequence: int = -1,
        *,
        through_sequence: int,
        limit: int = 256,
    ) -> tuple[TaskHandoffHeader, ...]: ...

    def read_latest_handoff_commit(
        self,
        task_id: TaskId,
        source_segment_id: SessionId,
        handoff_id: UUID,
        before_sequence: int,
        *,
        through_sequence: int,
    ) -> TaskHandoffHeader | None: ...


class FencedAgentTaskStorePort(AgentTaskPort, Protocol):
    """Cloud Task extension for Worker-owned Segment rollover."""

    def attach_segment_for_worker(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        *,
        predecessor_id: SessionId,
        reason: RolloverReason,
        authority: WorkerMutationAuthority,
    ) -> AgentTask: ...
