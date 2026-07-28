from dataclasses import dataclass
from datetime import datetime, timedelta

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import DEFAULT_MAX_LEASE_TTL, WorkerLease
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
        *,
        maximum_lease_ttl: timedelta = DEFAULT_MAX_LEASE_TTL,
    ) -> None:
        if maximum_lease_ttl <= timedelta(0):
            raise ValueError("maximum lease ttl must be positive")
        self._lease_store = lease_store
        self._recovery_service = recovery_service
        self._maximum_lease_ttl = maximum_lease_ttl

    def claim_session(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_ttl_seconds: int,
    ) -> ClaimedSession:
        self._require_aware(claimed_at)
        ttl = self._ttl(lease_ttl_seconds)
        lease = self._lease_store.acquire(
            session_id,
            owner_instance_id=worker_id,
            ttl=ttl,
        )
        try:
            recovery = self._recovery_service.recover_session(session_id)
            lease = self._lease_store.heartbeat(
                session_id,
                fence=lease.fence,
                ttl=ttl,
                checkpoint=recovery.last_sequence,
            )
        except BaseException as error:
            try:
                self._lease_store.release(session_id, fence=lease.fence)
            except Exception as release_error:
                error.add_note(f"lease cleanup failed: {release_error}")
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
        self._require_aware(heartbeat_at)
        ttl = self._ttl(lease_ttl_seconds)
        next_checkpoint = claimed.lease.checkpoint if checkpoint is None else checkpoint
        lease = self._lease_store.heartbeat(
            claimed.lease.session_id,
            fence=claimed.lease.fence,
            ttl=ttl,
            checkpoint=next_checkpoint,
        )
        return ClaimedSession(recovery=claimed.recovery, lease=lease)

    def release_claim(self, claimed: ClaimedSession) -> None:
        self._lease_store.release(
            claimed.lease.session_id,
            fence=claimed.lease.fence,
        )

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("claim timestamps must be timezone-aware")

    def _ttl(self, seconds: int) -> timedelta:
        maximum_seconds = self._maximum_lease_ttl.total_seconds()
        if seconds <= 0:
            raise ValueError("lease ttl must be positive")
        if seconds > maximum_seconds:
            raise ValueError("lease ttl exceeds configured maximum")
        return timedelta(seconds=seconds)
