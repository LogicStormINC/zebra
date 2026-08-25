"""Bounded recovery of Cloud Memory finalization after a lost Worker response."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_core.application import SessionTitleService
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseConflictError
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import (
    EventStorePort,
    GovernedMemoryStorePort,
    ProjectionStorePort,
    WorkspaceProjectionStorePort,
)

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.cloud_memory_finalization import finalize_cloud_memory
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat
from zebra_agent_worker.recovery import SessionRecoveryError
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory

TITLE_RETRY_COOLDOWN = timedelta(minutes=15)


class CloudMemoryFinalizationRecovery:
    """Finalize recently completed Cloud sessions without resuming their harness."""

    def __init__(
        self,
        *,
        claim_service: SessionClaimService,
        recorder_factory: WorkerProjectionRecorderFactory,
        memory_store: GovernedMemoryStorePort,
        deployment_namespace: str,
        event_store: EventStorePort,
        projection_store: ProjectionStorePort,
        workspace_store: WorkspaceProjectionStorePort,
        title_service_factory: Callable[[], SessionTitleService],
    ) -> None:
        self._claim_service = claim_service
        self._recorder_factory = recorder_factory
        self._memory_store = memory_store
        self._deployment_namespace = deployment_namespace
        self._event_store = event_store
        self._title_attempts: dict[SessionId, datetime] = {}
        self._projection_store = projection_store
        self._workspace_store = workspace_store
        self._title_service_factory = title_service_factory

    def recover(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        recovered_at: datetime,
        lease_ttl_seconds: int,
    ) -> bool:
        claimed = self._claim_service.claim_session(
            session_id,
            worker_id=worker_id,
            claimed_at=recovered_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        with LeaseHeartbeat(
            self._claim_service,
            claimed.lease,
            lease_ttl_seconds=lease_ttl_seconds,
        ) as heartbeat:
            if claimed.recovery.session.status not in {
                SessionStatus.COMPLETED,
                SessionStatus.AWAITING_TURN,
            }:
                return False
            recorder = self._recorder_factory.build(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                lease=claimed.lease,
                ownership_check=heartbeat.require_owned,
            )
            finalized = finalize_cloud_memory(
                recorder=recorder,
                memory_store=self._memory_store,
                deployment_namespace=self._deployment_namespace,
                event_store=self._event_store,
                projection_store=self._projection_store,
                workspace_store=self._workspace_store,
                # The recovery claim holds the lease and a fenced recorder:
                # commit the missing side chain instead of no-oping on it
                # (ADR-026 §6 — the crash-before-commit case).
                started_at=recovered_at,
                allow_commit=True,
            )
            if not finalized:
                return False
            events = self._event_store.list_for_session(session_id)
            if any(event.event_type is EventType.SESSION_TITLE_UPDATED for event in events):
                return True
            now = recovered_at
            last_attempt = self._title_attempts.get(session_id)
            if last_attempt is not None and now - last_attempt < TITLE_RETRY_COOLDOWN:
                # generate() returning None (provider failure, blank or
                # unchanged title) leaves no durable marker: without a
                # cooldown the scan would re-bill the title model on
                # every poll for every recent session.
                return True
            self._title_attempts[session_id] = now
            title_event = self._title_service_factory().generate(
                session=recorder.session,
                events=events,
                next_sequence=recorder.next_sequence,
            )
            if title_event is not None:
                recorder.append_event(title_event)
                self._title_attempts.pop(session_id, None)
            return True


def recover_completed_cloud_memory(
    *,
    worker_id: str,
    batch_size: int,
    lease_ttl_seconds: int,
    recovery: Any,
    projection_store: Any,
) -> None:
    if recovery is None:
        return
    # ponytail: retain a bounded recent window until an explicit durable
    # finalization queue is introduced for high-throughput deployments.
    for session in projection_store.list_recent_sessions(limit=max(batch_size, 32)):
        # COMPLETED: legacy/one-shot finalization; AWAITING_TURN: a
        # conversation Turn closed but its fenced Memory/title side
        # chain may still be missing after a Worker crash (ADR-026 §6).
        if session.status not in {
            SessionStatus.COMPLETED,
            SessionStatus.AWAITING_TURN,
        }:
            continue
        try:
            recovery.recover(
                session.session_id,
                worker_id=worker_id,
                recovered_at=datetime.now(UTC),
                lease_ttl_seconds=lease_ttl_seconds,
            )
        except (
            LeaseConflictError,
            SessionRecoveryError,
            WorkerExecutionError,
            ValueError,
        ):
            continue
