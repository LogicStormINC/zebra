from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Thread
from uuid import UUID

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_storage import (
    LeaseConflictError,
)

from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService
from zebra_agent_worker.cloud_memory_recovery import (
    CloudMemoryFinalizationRecovery,
    recover_completed_cloud_memory,
)
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeatError
from zebra_agent_worker.recovery import SessionRecoveryError
from zebra_agent_worker.resume import SessionResumeError
from zebra_agent_worker.worker_polling import has_remaining_cycles, validate_loop_inputs


@dataclass(frozen=True)
class WorkerLoopCycleResult:
    ready_session_ids: tuple[str, ...]
    executed_session_ids: tuple[str, ...]
    skipped_session_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkerLoopRunResult:
    cycles_completed: int
    idle_cycles: int
    stop_reason: str
    executed_session_ids: tuple[str, ...]
    skipped_session_ids: tuple[str, ...]


@dataclass
class _LoopAccumulator:
    cycles_completed: int = 0
    idle_cycles: int = 0
    executed_session_ids: list[str] = field(default_factory=list)
    skipped_session_ids: list[str] = field(default_factory=list)


def _task_binding_id(tasks: AgentTaskPort, session_id: SessionId) -> TaskId:
    """Keep one frozen Host binding across internal Task Segments."""

    return tasks.ensure_for_session(session_id).task_id


class WorkerLoopService:
    def __init__(
        self,
        projection_store: ProjectionStorePort,
        execution_service: SessionExecutionService,
        *,
        cloud_memory_recovery: CloudMemoryFinalizationRecovery | None = None,
        child_wakeup_service: ChildCompletionWakeupService | None = None,
        sleep: Callable[[float], None] = time.sleep,
        command_consumer: SessionCommandConsumer | None = None,
        scan_ready_sessions: bool = True,
        migrated_run: Callable[..., WorkerLoopRunResult] | None = None,
        cutover_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._projection_store = projection_store
        self._execution_service = execution_service
        self._cloud_memory_recovery = cloud_memory_recovery
        self._child_wakeup_service = child_wakeup_service
        self._sleep = sleep
        self._command_consumer = command_consumer
        self._scan_ready_sessions = scan_ready_sessions
        self._cloud_memory_recovery_thread: Thread | None = None
        self.migrated_run = migrated_run
        self._cutover_probe = cutover_probe

    def maintenance_once(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_ttl_seconds: int,
    ) -> None:
        self._process_child_wakeups()
        self._start_cloud_memory_recovery(
            worker_id=worker_id, batch_size=batch_size, lease_ttl_seconds=lease_ttl_seconds
        )

    def drain(self) -> None:
        if self._cloud_memory_recovery_thread is not None:
            self._cloud_memory_recovery_thread.join()

    def poll_once(
        self,
        *,
        worker_id: str,
        batch_size: int = 1,
        lease_ttl_seconds: int = 30,
    ) -> WorkerLoopCycleResult:
        self._process_child_wakeups()
        command_result = (
            self._command_consumer.consume_once(
                worker_id=worker_id,
                lease_ttl_seconds=lease_ttl_seconds,
                batch_size=batch_size,
            )
            if self._command_consumer is not None
            else None
        )
        executed_ids: list[str] = []
        skipped_ids: list[str] = []
        if command_result is not None and command_result.session_id is not None:
            if command_result.status == "executed":
                executed_ids.append(command_result.session_id)
            elif command_result.status == "skipped":
                skipped_ids.append(command_result.session_id)
                print(
                    f"worker command skipped: session={command_result.session_id} "
                    f"kind={command_result.command_kind} reason={command_result.reason}",
                    file=sys.stderr,
                    flush=True,
                )
        ready_sessions = (
            self._projection_store.list_ready_sessions(limit=batch_size)
            if self._scan_ready_sessions
            else []
        )
        ready_ids = tuple(str(session.session_id) for session in ready_sessions)
        for session in ready_sessions:
            session_id = str(session.session_id)
            if session_id in executed_ids:
                continue
            try:
                self._execution_service.execute_session(
                    session.session_id,
                    worker_id=worker_id,
                    lease_ttl_seconds=lease_ttl_seconds,
                )
            except (
                LeaseConflictError,
                SessionRecoveryError,
                SessionResumeError,
                WorkerExecutionError,
                ExecutionInterrupted,
                LeaseHeartbeatError,
                LeaseLostError,
            ) as skip_error:
                skipped_ids.append(session_id)
                print(
                    f"worker session skipped: session={session_id} "
                    f"reason={type(skip_error).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            executed_ids.append(session_id)
        if command_result is None or command_result.status == "idle":
            self._start_cloud_memory_recovery(
                worker_id=worker_id,
                batch_size=batch_size,
                lease_ttl_seconds=lease_ttl_seconds,
            )
        return WorkerLoopCycleResult(
            ready_session_ids=ready_ids,
            executed_session_ids=tuple(executed_ids),
            skipped_session_ids=tuple(skipped_ids),
        )

    def _start_cloud_memory_recovery(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_ttl_seconds: int,
    ) -> None:
        if self._cloud_memory_recovery is None:
            return
        active = self._cloud_memory_recovery_thread
        if active is not None and active.is_alive():
            return

        # ponytail: finalization recovery is best-effort background work until
        # it has its own durable queue; it must never block RUN command polling.
        def recover() -> None:
            try:
                recover_completed_cloud_memory(
                    worker_id=worker_id,
                    batch_size=batch_size,
                    lease_ttl_seconds=lease_ttl_seconds,
                    recovery=self._cloud_memory_recovery,
                    projection_store=self._projection_store,
                )
            except Exception:
                print("worker memory recovery failed", file=sys.stderr, flush=True)

        recovery_thread = Thread(
            target=recover,
            name=f"{worker_id}-cloud-memory-recovery",
            daemon=True,
        )
        self._cloud_memory_recovery_thread = recovery_thread
        recovery_thread.start()

    def _process_child_wakeups(self) -> None:
        """Poll terminal children and emit parent resume commands."""

        if self._child_wakeup_service is None:
            return
        from agent_core.domain.identifiers import TaskId
        from agent_core.domain.parent_continuation import ChildTerminalStatus

        for terminal in self._child_wakeup_service.poll_terminal_children():
            try:
                self._child_wakeup_service.process_child_terminal(
                    TaskId(UUID(str(terminal["child_task_id"]))),
                    status=ChildTerminalStatus(str(terminal["status"])),
                )
            except Exception:
                print(
                    "worker child wakeup failed",
                    file=sys.stderr,
                    flush=True,
                )

    def run(
        self,
        *,
        worker_id: str,
        batch_size: int = 1,
        lease_ttl_seconds: int = 30,
        max_cycles: int | None = None,
        stop_when_idle: bool = False,
        idle_sleep_seconds: float = 0.1,
    ) -> WorkerLoopRunResult:
        try:
            if self.migrated_run is not None:
                return self.migrated_run(
                    worker_id=worker_id,
                    batch_size=batch_size,
                    lease_ttl_seconds=lease_ttl_seconds,
                    max_cycles=max_cycles,
                    stop_when_idle=stop_when_idle,
                    idle_sleep_seconds=idle_sleep_seconds,
                )
            validate_loop_inputs(
                batch_size=batch_size,
                lease_ttl_seconds=lease_ttl_seconds,
                max_cycles=max_cycles,
                idle_sleep_seconds=idle_sleep_seconds,
            )
            accumulator = _LoopAccumulator()
            stop_reason = "max_cycles"
            while max_cycles is None or accumulator.cycles_completed < max_cycles:
                if self._cutover_probe is not None and self._cutover_probe():
                    stop_reason = "cutover_requires_restart"
                    break
                cycle = self.poll_once(
                    worker_id=worker_id,
                    batch_size=batch_size,
                    lease_ttl_seconds=lease_ttl_seconds,
                )
                accumulator.cycles_completed += 1
                accumulator.executed_session_ids.extend(cycle.executed_session_ids)
                accumulator.skipped_session_ids.extend(cycle.skipped_session_ids)
                if not cycle.ready_session_ids:
                    accumulator.idle_cycles += 1
                    if stop_when_idle:
                        stop_reason = "idle"
                        break
                    if not has_remaining_cycles(accumulator, max_cycles):
                        break
                    self._sleep(idle_sleep_seconds)
                    continue
                if (
                    stop_when_idle
                    and not cycle.executed_session_ids
                    and len(cycle.skipped_session_ids) == len(cycle.ready_session_ids)
                ):
                    stop_reason = "blocked"
                    break
                if not has_remaining_cycles(accumulator, max_cycles):
                    break
            return WorkerLoopRunResult(
                cycles_completed=accumulator.cycles_completed,
                idle_cycles=accumulator.idle_cycles,
                stop_reason=stop_reason,
                executed_session_ids=tuple(accumulator.executed_session_ids),
                skipped_session_ids=tuple(accumulator.skipped_session_ids),
            )
        finally:
            self.drain()
