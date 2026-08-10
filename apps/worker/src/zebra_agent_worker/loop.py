from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from agent_core.domain.identifiers import SessionId
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    LeaseConflictError,
    compose_control_plane_stores,
)
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.control import SessionControlService
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.provider_continuation_commit import (
    CloudProviderContinuationCoordinator,
)
from zebra_agent_worker.recovery import SessionRecoveryError, SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeError, SessionResumeService


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


class WorkerLoopService:
    def __init__(
        self,
        projection_store: ProjectionStorePort,
        execution_service: SessionExecutionService,
        *,
        sleep: Callable[[float], None] = time.sleep,
        command_consumer: SessionCommandConsumer | None = None,
    ) -> None:
        self._projection_store = projection_store
        self._execution_service = execution_service
        self._sleep = sleep
        self._command_consumer = command_consumer

    def poll_once(
        self,
        *,
        worker_id: str,
        batch_size: int = 1,
        lease_ttl_seconds: int = 30,
    ) -> WorkerLoopCycleResult:
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
        ready_sessions = self._projection_store.list_ready_sessions(limit=batch_size)
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
            except (LeaseConflictError, SessionRecoveryError, SessionResumeError):
                skipped_ids.append(session_id)
                continue
            executed_ids.append(session_id)
        return WorkerLoopCycleResult(
            ready_session_ids=ready_ids,
            executed_session_ids=tuple(executed_ids),
            skipped_session_ids=tuple(skipped_ids),
        )

    def run(
        self,
        *,
        worker_id: str,
        batch_size: int = 1,
        lease_ttl_seconds: int = 30,
        max_cycles: int | None = None,
        stop_when_idle: bool = False,
        idle_sleep_seconds: float = 1.0,
    ) -> WorkerLoopRunResult:
        _validate_loop_inputs(
            batch_size=batch_size,
            lease_ttl_seconds=lease_ttl_seconds,
            max_cycles=max_cycles,
            idle_sleep_seconds=idle_sleep_seconds,
        )
        accumulator = _LoopAccumulator()
        stop_reason = "max_cycles"
        while max_cycles is None or accumulator.cycles_completed < max_cycles:
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
                if not _has_remaining_cycles(accumulator, max_cycles):
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
            if not _has_remaining_cycles(accumulator, max_cycles):
                break
        return WorkerLoopRunResult(
            cycles_completed=accumulator.cycles_completed,
            idle_cycles=accumulator.idle_cycles,
            stop_reason=stop_reason,
            executed_session_ids=tuple(accumulator.executed_session_ids),
            skipped_session_ids=tuple(accumulator.skipped_session_ids),
        )


def build_worker_loop_service(
    *,
    database_path: Path,
    settings: ZebraAgentSettings,
    sleep: Callable[[float], None] = time.sleep,
    stores: ControlPlaneStores | None = None,
    cloud_composition: CloudCompositionSettings | None = None,
    effect_dispatch: EffectDispatchPort | None = None,
    worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
    deployment_namespace: str | None = None,
    cloud_provider_continuation_factory: Callable[[SessionId], CloudProviderContinuationCoordinator]
    | None = None,
) -> WorkerLoopService:
    active_stores = stores or compose_control_plane_stores(
        profile=settings.profile,
        storage_authority=settings.storage_authority,
        database_path=(
            settings.database_url
            if settings.storage_authority == "postgresql"
            else database_path
        ),
        cloud=cloud_composition,
    )
    active_transaction = worker_projection_transaction
    active_namespace = deployment_namespace
    if settings.storage_authority == "postgresql":
        active_transaction = active_transaction or cast(
            WorkerProjectionTransactionPort, active_stores.workspaces
        )
        active_namespace = active_namespace or getattr(active_stores, "deployment_namespace", None)
        if not isinstance(active_namespace, str) or not active_namespace.strip():
            raise ValueError(
                f"{settings.profile} profile composition must expose deployment_namespace"
            )
    claim_service = SessionClaimService(
        active_stores.leases,
        SessionRecoveryService(
            active_stores.events,
            active_stores.sessions,
            active_stores.workspaces,
        ),
    )
    execution_service = SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=settings,
        stores=active_stores,
        effect_dispatch=effect_dispatch,
        worker_projection_transaction=active_transaction,
        deployment_namespace=active_namespace,
        cloud_provider_continuation_factory=cloud_provider_continuation_factory,
    )
    command_consumer = SessionCommandConsumer(
        active_stores,
        execution_service,
        control_service=SessionControlService(
            database_path,
            settings=settings,
            stores=active_stores,
        ),
    )
    return WorkerLoopService(
        projection_store=active_stores.sessions,
        execution_service=execution_service,
        sleep=sleep,
        command_consumer=command_consumer,
    )


def _has_remaining_cycles(accumulator: _LoopAccumulator, max_cycles: int | None) -> bool:
    return max_cycles is None or accumulator.cycles_completed < max_cycles


def _validate_loop_inputs(
    *,
    batch_size: int,
    lease_ttl_seconds: int,
    max_cycles: int | None,
    idle_sleep_seconds: float,
) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if lease_ttl_seconds <= 0:
        raise ValueError("lease_ttl_seconds must be greater than zero")
    if max_cycles is not None and max_cycles <= 0:
        raise ValueError("max_cycles must be greater than zero when provided")
    if idle_sleep_seconds < 0:
        raise ValueError("idle_sleep_seconds must not be negative")
