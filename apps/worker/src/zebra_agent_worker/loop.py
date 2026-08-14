from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from agent_core.domain.identifiers import SessionId
from agent_core.ports import EffectDispatchPort, WorkerProjectionTransactionPort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_integrations import RedisCommittedEventPublisher
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    LeaseConflictError,
    PostgresControlPlaneStores,
    cloud_composition_from_environment,
    with_committed_event_publisher,
)
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.cloud_composition import CloudWorkerComposition, compose_cloud_worker
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
    cloud_worker_composition: CloudWorkerComposition | None = None,
    effect_dispatch: EffectDispatchPort | None = None,
    worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
    deployment_namespace: str | None = None,
    cloud_provider_continuation_factory: Callable[[SessionId], CloudProviderContinuationCoordinator]
    | None = None,
) -> WorkerLoopService:
    if settings.storage_authority == "postgresql":
        if stores is not None:
            raise ValueError("cloud Worker requires CloudWorkerComposition, not ControlPlaneStores")
        if any(
            value is not None
            for value in (
                effect_dispatch,
                worker_projection_transaction,
                deployment_namespace,
                cloud_provider_continuation_factory,
            )
        ):
            raise ValueError("cloud Worker dependencies must come from one CloudWorkerComposition")
        cloud_bundle = cloud_worker_composition or compose_cloud_worker(
            cloud_composition or cloud_composition_from_environment()
        )
        active_stores: ControlPlaneStores | PostgresControlPlaneStores = cloud_bundle.stores
        active_transaction: WorkerProjectionTransactionPort | None = (
            cloud_bundle.projection_transaction
        )
        active_namespace: str | None = cloud_bundle.deployment_namespace
        active_dispatch: EffectDispatchPort | None = cloud_bundle.effect_dispatch
        active_artifact_factory = cloud_bundle.artifact_factory
        active_provider_factory: (
            Callable[[SessionId], CloudProviderContinuationCoordinator] | None
        ) = (
            cloud_bundle.provider_continuation_factory
        )
    else:
        from agent_storage import sqlite_control_plane_stores

        active_stores = stores or sqlite_control_plane_stores(database_path)
        active_transaction = worker_projection_transaction
        active_namespace = deployment_namespace
        active_dispatch = effect_dispatch
        active_artifact_factory = None
        active_provider_factory = cloud_provider_continuation_factory
    if settings.live_events.redis_url is not None:
        namespace = getattr(active_stores, "deployment_namespace", None)
        if namespace is None and settings.deployment == "local":
            namespace = "local"
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("live Redis publishing requires deployment_namespace")
        active_stores = with_committed_event_publisher(
            active_stores,
            RedisCommittedEventPublisher.from_url(
                settings.live_events.redis_url,
                deployment_namespace=namespace,
                max_stream_length=settings.live_events.stream_max_length,
                key_prefix=settings.live_events.key_prefix,
            ),
        )
    execution_stores = active_stores
    claim_service = SessionClaimService(
        execution_stores.leases,
        SessionRecoveryService(
            execution_stores.events,
            execution_stores.sessions,
            execution_stores.workspaces,
        ),
    )
    execution_service = SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=settings,
        stores=execution_stores,
        effect_dispatch=active_dispatch,
        worker_projection_transaction=active_transaction,
        deployment_namespace=active_namespace,
        cloud_artifact_factory=active_artifact_factory,
        cloud_provider_continuation_factory=active_provider_factory,
    )
    command_consumer = SessionCommandConsumer(
        execution_stores,
        execution_service,
        control_service=SessionControlService(
            database_path,
            settings=settings,
            stores=execution_stores,
        ),
    )
    return WorkerLoopService(
        projection_store=execution_stores.sessions,
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
