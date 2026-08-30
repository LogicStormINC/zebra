from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from uuid import UUID

import httpx
from agent_core.application import SessionTitleService
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.leases import LeaseLostError
from agent_core.ports import (
    EffectDispatchPort,
    GovernedMemoryStorePort,
    WorkerProjectionTransactionPort,
)
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_integrations import build_model_gateway
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    LeaseConflictError,
    PostgresControlPlaneStores,
    cloud_composition_from_environment,
)
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService
from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.client_effect_runtime import compose_client_runtime
from zebra_agent_worker.cloud_composition import CloudWorkerComposition, compose_cloud_worker
from zebra_agent_worker.cloud_memory_recovery import (
    CloudMemoryFinalizationRecovery,
    recover_completed_cloud_memory,
)
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.control import SessionControlService
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeatError
from zebra_agent_worker.live_event_runtime import configure_live_event_delivery
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.provider_configuration import model_provider_settings
from zebra_agent_worker.provider_continuation_commit import (
    CloudProviderContinuationCoordinator,
)
from zebra_agent_worker.recovery import SessionRecoveryError, SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeError, SessionResumeService
from zebra_agent_worker.tool_run_index import ToolRunIndexer
from zebra_agent_worker.worker_polling import has_remaining_cycles, validate_loop_inputs
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory


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
    ) -> None:
        self._projection_store = projection_store
        self._execution_service = execution_service
        self._cloud_memory_recovery = cloud_memory_recovery
        self._child_wakeup_service = child_wakeup_service
        self._sleep = sleep
        self._command_consumer = command_consumer
        self._scan_ready_sessions = scan_ready_sessions
        self._cloud_memory_recovery_thread: Thread | None = None

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
                    f"reason={type(skip_error).__name__}: {skip_error}",
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
        recovery_thread = Thread(
            target=recover_completed_cloud_memory,
            kwargs={
                "worker_id": worker_id,
                "batch_size": batch_size,
                "lease_ttl_seconds": lease_ttl_seconds,
                "recovery": self._cloud_memory_recovery,
                "projection_store": self._projection_store,
            },
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
            except Exception as error:
                print(
                    f"worker child wakeup failed: {error}",
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
        validate_loop_inputs(
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
    model_http_client: httpx.Client | None = None,
) -> WorkerLoopService:
    client_runtime = None
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
        cloud_memory_store: GovernedMemoryStorePort | None = cloud_bundle.stores.memories
        active_transaction: WorkerProjectionTransactionPort | None = (
            cloud_bundle.projection_transaction
        )
        active_namespace: str | None = cloud_bundle.deployment_namespace
        active_dispatch: EffectDispatchPort | None = cloud_bundle.effect_dispatch
        active_artifact_factory = cloud_bundle.artifact_factory
        active_workspace_resolver_factory = cloud_bundle.workspace_resolver_factory
        active_provider_factory: (
            Callable[[SessionId], CloudProviderContinuationCoordinator] | None
        ) = cloud_bundle.provider_continuation_factory
        active_authority_resolver = cloud_bundle.authority_resolver
        active_authority_scope_provider = cloud_bundle.authority_scope_provider
        client_runtime = compose_client_runtime(
            cloud_bundle.dsn,
            deployment_namespace=active_namespace or "",
            enabled=settings.client_integration_enabled,
        )
    else:
        from agent_storage import sqlite_control_plane_stores

        active_stores = stores or sqlite_control_plane_stores(database_path)
        cloud_memory_store = None
        active_transaction = worker_projection_transaction
        active_namespace = deployment_namespace
        active_dispatch = effect_dispatch
        active_artifact_factory = None
        active_workspace_resolver_factory = None
        active_provider_factory = cloud_provider_continuation_factory
        active_authority_resolver = None
        active_authority_scope_provider = None
    active_stores, active_transaction = configure_live_event_delivery(
        active_stores,
        active_transaction,
        settings,
    )
    execution_stores = active_stores
    model_call_indexer = ModelCallIndexer(execution_stores.model_calls)
    tool_run_indexer = ToolRunIndexer(execution_stores.tool_runs)
    recovery_service = SessionRecoveryService(
        execution_stores.events,
        execution_stores.sessions,
        execution_stores.workspaces,
        worker_projection_transaction=active_transaction,
        deployment_namespace=active_namespace,
        model_call_indexer=(model_call_indexer if active_transaction is not None else None),
        tool_run_indexer=(tool_run_indexer if active_transaction is not None else None),
    )
    claim_service = SessionClaimService(
        execution_stores.leases,
        recovery_service,
    )
    task_binding_loader = None
    egress_registry = None
    delegation_store = None
    if cloud_memory_store is not None and settings.storage_authority == "postgresql":
        from agent_storage.postgres.task_admission import load_task_binding as _load_binding

        binding_dsn = cloud_bundle.dsn or ""
        if binding_dsn:

            def task_binding_loader(session_id: SessionId) -> object:
                assert active_namespace is not None
                return _load_binding(
                    binding_dsn,
                    deployment_namespace=active_namespace,
                    task_id=_task_binding_id(execution_stores.tasks, session_id),
                )

    frozen_manifest_loader = None
    if cloud_memory_store is not None and settings.storage_authority == "postgresql":
        from agent_storage.postgres.host_manifest_freeze import (
            load_frozen_manifest_by_digest as _load_frozen_manifest,
        )

        manifest_dsn = cloud_bundle.dsn or ""
        if manifest_dsn and active_namespace is not None:

            def frozen_manifest_loader(digest: str) -> object:
                assert active_namespace is not None
                return _load_frozen_manifest(
                    manifest_dsn,
                    deployment_namespace=active_namespace,
                    manifest_digest=digest,
                )

    child_wakeup_service = None
    if cloud_memory_store is not None and settings.storage_authority == "postgresql":
        from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService as _Wakeup

        wakeup_dsn = cloud_bundle.dsn or ""
        if wakeup_dsn and active_namespace is not None:
            child_wakeup_service = _Wakeup(wakeup_dsn, deployment_namespace=active_namespace)
            from agent_storage.postgres.host_connectors import (
                PostgresHostConnectorRegistry,
            )

            egress_registry = PostgresHostConnectorRegistry(
                wakeup_dsn, deployment_namespace=active_namespace
            )
            from agent_storage.postgres.subagent_delegation import (
                PostgresSubagentDelegationStore,
            )

            delegation_store = PostgresSubagentDelegationStore(
                wakeup_dsn, deployment_namespace=active_namespace
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
        task_binding_loader=task_binding_loader,
        egress_registry=egress_registry,
        delegation_store=delegation_store,
        frozen_manifest_loader=frozen_manifest_loader,
        client_runtime=client_runtime,
        model_http_client=model_http_client,
        cloud_artifact_factory=active_artifact_factory,
        cloud_provider_continuation_factory=active_provider_factory,
        workspace_resolver=(
            active_workspace_resolver_factory()
            if active_workspace_resolver_factory is not None
            else None
        ),
        execution_authority_resolver=active_authority_resolver,
        execution_authority_scope_provider=active_authority_scope_provider,
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
    cloud_memory_recovery = None
    if cloud_memory_store is not None:
        assert active_namespace is not None
        assert active_transaction is not None
        cloud_memory_recovery = CloudMemoryFinalizationRecovery(
            claim_service=claim_service,
            recorder_factory=WorkerProjectionRecorderFactory(
                stores=execution_stores,
                model_call_indexer=model_call_indexer,
                tool_run_indexer=tool_run_indexer,
                transaction=active_transaction,
                deployment_namespace=active_namespace,
            ),
            memory_store=cloud_memory_store,
            idempotency_store=execution_stores.idempotency,
            deployment_namespace=active_namespace,
            event_store=execution_stores.events,
            projection_store=execution_stores.sessions,
            workspace_store=execution_stores.workspaces,
            title_service_factory=lambda: SessionTitleService(
                build_model_gateway(
                    model_provider_settings(settings), client=model_http_client
                )
                if model_http_client is not None
                else build_model_gateway(model_provider_settings(settings))
            ),
        )
    return WorkerLoopService(
        projection_store=execution_stores.sessions,
        execution_service=execution_service,
        cloud_memory_recovery=cloud_memory_recovery,
        child_wakeup_service=child_wakeup_service,
        sleep=sleep,
        command_consumer=command_consumer,
        scan_ready_sessions=settings.deployment != "cloud",
    )
