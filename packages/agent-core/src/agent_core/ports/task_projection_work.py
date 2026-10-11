"""Durable derived-work scheduling only; never execution authority or SSE repair."""

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import ProjectionScope

MAX_PENDING_PROJECTION_WORK = 32
MAX_PROJECTION_WORK_REPAIR = 256
MAX_ENABLED_PROJECTORS = 4
MAX_PROJECTION_WORK_BYTES = 1_048_576
PROJECTION_WORK_SECONDS = 2.0
PROJECTION_PROBLEM_CODES = frozenset({"not_ready", "integrity", "budget", "projection_failed"})


def _position(value: int, minimum: int = -1) -> None:
    if type(value) is not int or not minimum <= value <= 9_223_372_036_854_775_807:
        raise ValueError("invalid projection-work position")


@dataclass(frozen=True, slots=True)
class ProjectionWork:
    scope: ProjectionScope
    run_id: str
    anchor_sequence: int
    requested_through: int
    revision: int
    after_sequence: int
    closed_through: int | None = None

    def __post_init__(self) -> None:
        if self.scope.anchor_event_id is None:
            raise ValueError("projection work requires an executable anchor")
        if not isinstance(self.run_id, str) or not self.run_id or len(self.run_id) > 256:
            raise ValueError("invalid projection-work Run identity")
        _position(self.anchor_sequence, 0)
        _position(self.requested_through, self.anchor_sequence)
        _position(self.revision, 1)
        _position(self.after_sequence)
        if self.after_sequence > self.requested_through:
            raise ValueError("checkpoint frontier exceeds projection-work target")
        if self.closed_through is not None:
            _position(self.closed_through, self.anchor_sequence)
            if self.closed_through != self.requested_through:
                raise ValueError("closed projection-work target is immutable")


@dataclass(frozen=True, slots=True)
class ProjectionWorkRepair:
    scope: ProjectionScope
    after_sequence: int
    wanted_through: int
    needs_repair: bool

    def __post_init__(self) -> None:
        if self.scope.anchor_event_id is not None:
            raise ValueError("routing repair is Task/version scoped")
        _position(self.after_sequence)
        _position(self.wanted_through, self.after_sequence)
        if type(self.needs_repair) is not bool or (
            not self.needs_repair and self.after_sequence < self.wanted_through
        ):
            raise ValueError("projection-work repair frontier disagrees")


@dataclass(frozen=True, slots=True)
class ProjectionWorkProblem:
    scope: ProjectionScope
    code: str
    attempts: int
    retry_at: float | None

    def __post_init__(self) -> None:
        if self.scope.anchor_event_id is None or self.code not in PROJECTION_PROBLEM_CODES:
            raise ValueError("invalid projection-work problem")
        _position(self.attempts, 0 if self.code == "not_ready" and self.retry_at is None else 1)
        if self.retry_at is not None and not 0 < self.retry_at < float("inf"):
            raise ValueError("invalid projection-work retry time")


class TaskProjectionWorkPort(Protocol):
    """Store is bound to one namespace/version; construction and reads are inert.

    Native source-position/scalar-header hooks route only contiguous confirmed
    headers. A gap becomes durable repair-needed, never request-time adoption.
    At most four enabled versions receive a wake. Old Run targets close at the
    next executable's position minus one; control/internal resumes do not open
    Runs. No claim leases: duplicate builders use the existing checkpoint CAS.

    pending reads return <=32 scalar rows and the *existing* checkpoint frontier
    (or -1), never bodies/cells or a synthetic initialized checkpoint. after_scope
    permits a bounded round-robin poll; callers wrap to None after an empty page.
    repair is explicitly invoked maintenance, <=256 scalar headers per call.
    Row/byte/time limits may return a shorter durable contiguous prefix; resume
    from that returned frontier, never assume a requested page was filled.
    complete requires the actual head/frontier and exact wake revision/target;
    False leaves work pending. It never commits a checkpoint or executes a Task.
    """

    def enable_projection_work(self) -> None: ...

    def disable_projection_work(self) -> None: ...

    def bootstrap_projection_work(self, *, limit: int = 32) -> bool:
        """Explicit <=32 Task-head seek; True closes discovery, not materialization."""
        ...

    def read_pending_projection_work(
        self,
        *,
        limit: int = 32,
        after_scope: ProjectionScope | None = None,
    ) -> tuple[ProjectionWork, ...]: ...

    def read_projection_work_repairs(
        self,
        *,
        limit: int = 32,
        after_task_id: TaskId | None = None,
    ) -> tuple[ProjectionWorkRepair, ...]: ...

    def repair_projection_work(
        self,
        task_id: TaskId,
        *,
        limit: int = 256,
    ) -> ProjectionWorkRepair: ...

    def complete_projection_work(
        self,
        work: ProjectionWork,
        *,
        expected_through: int,
    ) -> bool: ...

    def defer_projection_work(
        self,
        work: ProjectionWork,
        *,
        problem_code: str,
        retry_after_seconds: float | None = None,
    ) -> bool:
        """Untimed not_ready is a dependency wait, not a failure attempt.

        Waiting and its confirmed append/closure wake preserve the failure count.
        Timed, integrity and exhausted faults remain deferred across append.
        Only explicit operator retry reopens exhausted faults. Repair pages cost none.
        """
        ...

    def read_projection_work_problem(
        self,
        scope: ProjectionScope,
    ) -> ProjectionWorkProblem | None: ...

    def retry_due_projection_work(self, *, limit: int = 32) -> int: ...

    def retry_projection_work(
        self,
        scope: ProjectionScope,
        *,
        expected_attempt: int,
    ) -> bool: ...
