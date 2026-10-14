"""Optional fresh metadata heads for cloud stream observers."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.task_projection_checkpoints import (
    ProjectionCell,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    SegmentCheckpoint,
)
from agent_core.ports.task_replay import TaskEventHeader, TaskReadHeader, TaskRunHeader


@dataclass(frozen=True, slots=True)
class StreamSourceHead:
    task: TaskReadHeader
    session_sequence: int | None = None
    session_status: SessionStatus | None = None


@dataclass(frozen=True, slots=True)
class StreamCheckpointHead:
    run: TaskRunHeader
    head: ProjectionCheckpointHead
    command_outcome: str | None = None


class StreamCheckpointReadPort(Protocol):
    def read_checkpoint_head(self, scope: ProjectionScope) -> ProjectionCheckpointHead: ...
    def read_event_projection_header(
        self, scope: ProjectionScope, task_sequence: int
    ) -> ProjectionFrameHeader | None: ...
    def read_segment_checkpoint_before(
        self, scope: ProjectionScope, segment_id: SessionId, before_sequence: int
    ) -> SegmentCheckpoint: ...
    def read_cells_at(
        self, scope: ProjectionScope, before_sequence: int, keys: tuple[ProjectionCellKey, ...]
    ) -> tuple[ProjectionCell, ...]: ...


class StreamObservationReadPort(Protocol):
    """Optional initial observation metadata; no projection writes or body restore."""

    def read_task_header(
        self, task_id: TaskId, *, require_source_coverage: bool = False
    ) -> TaskReadHeader | None: ...
    def read_stream_checkpoint_head(
        self,
        task_id: TaskId,
        run_id: str,
        *,
        ordinary_version: str,
        coverage_version: str,
        host_context: HostContextEnvelope | None = None,
    ) -> StreamCheckpointHead: ...
    def read_event_header(self, task_id: TaskId, task_sequence: int) -> TaskEventHeader | None: ...
    def read_event_projection_header(
        self, scope: ProjectionScope, task_sequence: int
    ) -> ProjectionFrameHeader | None: ...


@runtime_checkable
class StreamSourceHeadPort(Protocol):
    """Native adapters may expose stream_head_reads_compatible=False for fallback.

    ponytail: explicit nonnative implementations keep their existing opt-in contract.
    """

    def read_stream_source_head(
        self, *, task_id: TaskId | None = None, session_id: SessionId | None = None
    ) -> StreamSourceHead | None: ...

    def read_stream_checkpoint_head(
        self,
        task_id: TaskId,
        run_id: str,
        *,
        ordinary_version: str,
        coverage_version: str,
        host_context: HostContextEnvelope | None = None,
    ) -> StreamCheckpointHead: ...

    def read_checkpoint_snapshot(
        self, scope: ProjectionScope, position: int
    ) -> AbstractContextManager[StreamCheckpointReadPort]: ...
