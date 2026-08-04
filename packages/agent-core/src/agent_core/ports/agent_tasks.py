from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.agent_tasks import AgentTask, ExecutionSegment, RolloverReason
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority


@dataclass(frozen=True, slots=True)
class TaskEvent:
    task_id: TaskId
    task_sequence: int
    segment_id: SessionId
    segment_sequence: int
    event: SessionEvent


class AgentTaskPort(Protocol):
    def ensure_for_session(self, session_id: SessionId) -> AgentTask: ...

    def get_task(self, task_id: TaskId) -> AgentTask | None: ...

    def list_tasks(self, *, limit: int) -> tuple[AgentTask, ...]: ...

    def segments(self, task_id: TaskId) -> tuple[ExecutionSegment, ...]: ...

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
