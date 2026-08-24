"""Bounded recovery of Cloud Memory finalization after a lost Worker response."""

from collections.abc import Callable
from datetime import datetime

from agent_core.application import SessionTitleService
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import (
    EventStorePort,
    GovernedMemoryStorePort,
    ProjectionStorePort,
    WorkspaceProjectionStorePort,
)

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.cloud_memory_finalization import finalize_cloud_memory
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory


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
                started_at=recovered_at,
                allow_commit=False,
            )
            if not finalized:
                return False
            events = self._event_store.list_for_session(session_id)
            if any(event.event_type is EventType.SESSION_TITLE_UPDATED for event in events):
                return True
            title_event = self._title_service_factory().generate(
                session=recorder.session,
                events=events,
                next_sequence=recorder.next_sequence,
            )
            if title_event is not None:
                recorder.append_event(title_event)
            return True
