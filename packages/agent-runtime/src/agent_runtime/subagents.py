from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock

from agent_core.domain.identifiers import SubagentId, new_subagent_id
from agent_core.domain.subagents import (
    ResearchSubagentResult,
    ResearchSubagentTask,
    SubagentStatus,
)
from agent_core.ports.subagents import SubagentPort

PROVENANCE = "local_read_only_research"
ResearchRunner = Callable[
    [SubagentId, ResearchSubagentTask, Event],
    ResearchSubagentResult,
]


class SubagentStageError(RuntimeError):
    """Typed failure carrying a safe stage and reason code (no payloads)."""

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage} {reason}")
        self.stage = stage
        self.reason = reason


class SubagentLimitError(ValueError):
    """Raised before work starts when a child-agent bound would be exceeded."""


class UnknownSubagentError(KeyError):
    """Raised when a child-agent identifier is not owned by this coordinator."""


@dataclass
class _ChildRecord:
    cancel_requested: Event
    future: Future[ResearchSubagentResult]
    cancelled_result: ResearchSubagentResult | None = None


class LocalResearchSubagentCoordinator(SubagentPort):
    def __init__(
        self,
        runner: ResearchRunner,
        *,
        max_children: int = 1,
        max_concurrency: int = 1,
        max_depth: int = 1,
        max_model_calls: int = 3,
        max_tool_calls: int = 2,
    ) -> None:
        if min(
            max_children,
            max_concurrency,
            max_depth,
            max_model_calls,
            max_tool_calls,
        ) <= 0:
            raise ValueError("subagent limits must be positive")
        self._runner = runner
        self._max_children = max_children
        self._max_depth = max_depth
        self._max_model_calls = max_model_calls
        self._max_tool_calls = max_tool_calls
        self._executor = ThreadPoolExecutor(
            max_workers=min(max_children, max_concurrency),
            thread_name_prefix="zebra-research",
        )
        self._records: dict[SubagentId, _ChildRecord] = {}
        self._lock = Lock()
        self._closed = False
        self._delegation_attempted = False

    @property
    def delegation_attempted(self) -> bool:
        return self._delegation_attempted

    def _active_count_locked(self) -> int:
        return sum(
            1
            for record in self._records.values()
            if not record.future.done() and record.cancelled_result is None
        )

    def spawn(self, task: ResearchSubagentTask) -> SubagentId:
        with self._lock:
            if self._closed:
                raise SubagentLimitError("subagent coordinator is closed")
            # SUBAGENT-COORD-FIX-01: completed children never occupy slots.
            if self._active_count_locked() >= self._max_children:
                raise SubagentLimitError("subagent active child limit reached")
            if task.depth > self._max_depth:
                raise SubagentLimitError("subagent depth limit reached")
            if task.max_model_calls > self._max_model_calls:
                raise SubagentLimitError("subagent model-call limit reached")
            if task.max_tool_calls > self._max_tool_calls:
                raise SubagentLimitError("subagent tool-call limit reached")
            self._delegation_attempted = True
            subagent_id = new_subagent_id()
            cancellation = Event()
            future = self._executor.submit(
                self._run,
                subagent_id,
                task,
                cancellation,
            )
            self._records[subagent_id] = _ChildRecord(cancellation, future)
            return subagent_id

    def join(
        self,
        subagent_id: SubagentId,
        *,
        timeout_seconds: float | None = None,
    ) -> ResearchSubagentResult:
        # SUBAGENT-COORD-FIX-01: bounded join with a typed timeout failure.
        record = self._record(subagent_id)
        if record.cancelled_result is not None:
            return record.cancelled_result
        try:
            return record.future.result(timeout=timeout_seconds)
        except TimeoutError as exc:
            raise SubagentStageError(
                "stage=join",
                "reason=subagent_join_deadline_exceeded",
            ) from exc

    def cancel(self, subagent_id: SubagentId) -> bool:
        record = self._record(subagent_id)
        if record.cancelled_result is not None or record.future.done():
            return False
        record.cancel_requested.set()
        if record.future.cancel():
            record.cancelled_result = cancelled_result(subagent_id)
        return True

    def collect(self, subagent_id: SubagentId) -> ResearchSubagentResult | None:
        record = self._record(subagent_id)
        if record.cancelled_result is not None:
            return record.cancelled_result
        return record.future.result() if record.future.done() else None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            identifiers = tuple(self._records)
        for subagent_id in identifiers:
            self.cancel(subagent_id)
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _record(self, subagent_id: SubagentId) -> _ChildRecord:
        try:
            return self._records[subagent_id]
        except KeyError as exc:
            raise UnknownSubagentError(str(subagent_id)) from exc

    def _run(
        self,
        subagent_id: SubagentId,
        task: ResearchSubagentTask,
        cancellation: Event,
    ) -> ResearchSubagentResult:
        if cancellation.is_set():
            return cancelled_result(subagent_id)
        try:
            result = self._runner(subagent_id, task, cancellation)
        except Exception as exc:
            return ResearchSubagentResult(
                subagent_id=subagent_id,
                status=SubagentStatus.FAILED,
                summary=f"research subagent failed: {type(exc).__name__}",
                provenance=PROVENANCE,
            )
        if cancellation.is_set():
            return cancelled_result(subagent_id)
        if result.subagent_id != subagent_id:
            raise ValueError("research runner returned a mismatched subagent id")
        return result


def cancelled_result(subagent_id: SubagentId) -> ResearchSubagentResult:
    return ResearchSubagentResult(
        subagent_id=subagent_id,
        status=SubagentStatus.CANCELLED,
        summary="research subagent cancelled",
        provenance=PROVENANCE,
    )
