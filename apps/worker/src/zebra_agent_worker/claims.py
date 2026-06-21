from dataclasses import dataclass
from datetime import datetime, timedelta

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease
from agent_core.ports.lease_store import LeaseStorePort

from zebra_agent_worker.recovery import RecoveredSession, SessionRecoveryService


@dataclass(frozen=True)
class ClaimedSession:
    recovery: RecoveredSession
    lease: WorkerLease


class SessionClaimService:
    def __init__(
        self,
        lease_store: LeaseStorePort,
        recovery_service: SessionRecoveryService,
    ) -> None:
        self._lease_store = lease_store
        self._recovery_service = recovery_service

    def claim_session(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_ttl_seconds: int,
    ) -> ClaimedSession:
        recovery = self._recovery_service.recover_session(session_id)
        try:
            lease = self._lease_store.acquire(
                session_id,
                worker_id=worker_id,
                acquired_at=claimed_at,
                expires_at=claimed_at + timedelta(seconds=lease_ttl_seconds),
                checkpoint=recovery.last_sequence,
            )
        except Exception:
            raise
        return ClaimedSession(recovery=recovery, lease=lease)

    def heartbeat_claim(
        self,
        claimed: ClaimedSession,
        *,
        heartbeat_at: datetime,
        lease_ttl_seconds: int,
        checkpoint: int | None = None,
    ) -> ClaimedSession:
        next_checkpoint = claimed.lease.checkpoint if checkpoint is None else checkpoint
        lease = self._lease_store.heartbeat(
            claimed.lease.session_id,
            worker_id=claimed.lease.worker_id,
            heartbeat_at=heartbeat_at,
            expires_at=heartbeat_at + timedelta(seconds=lease_ttl_seconds),
            checkpoint=next_checkpoint,
        )
        return ClaimedSession(recovery=claimed.recovery, lease=lease)

    def release_claim(self, claimed: ClaimedSession) -> None:
        self._lease_store.release(
            claimed.lease.session_id,
            worker_id=claimed.lease.worker_id,
        )
