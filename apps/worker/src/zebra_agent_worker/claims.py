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
        lease = self.acquire_lease(
            session_id,
            worker_id=worker_id,
            claimed_at=claimed_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        try:
            return self.recover_lease(
                lease,
                lease_ttl_seconds=lease_ttl_seconds,
            )
        except BaseException as error:
            try:
                self._lease_store.release(session_id, fence=lease.fence)
            except Exception as release_error:
                error.add_note(f"lease cleanup failed: {release_error}")
            raise

    def acquire_lease(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_ttl_seconds: int,
    ) -> WorkerLease:
        self._require_aware(claimed_at)
        return self._lease_store.acquire(
            session_id,
            owner_instance_id=worker_id,
            ttl=self._ttl(lease_ttl_seconds),
        )

    def recover_lease(
        self,
        lease: WorkerLease,
        *,
        lease_ttl_seconds: int,
    ) -> ClaimedSession:
        recovery = self._recovery_service.recover_session(lease.session_id)
        renewed = self.heartbeat_lease(
            lease,
            lease_ttl_seconds=lease_ttl_seconds,
            checkpoint=recovery.last_sequence,
        )
        return ClaimedSession(recovery=recovery, lease=renewed)

    def heartbeat_claim(
        self,
        claimed: ClaimedSession,
        *,
        heartbeat_at: datetime,
        lease_ttl_seconds: int,
        checkpoint: int | None = None,
    ) -> ClaimedSession:
        self._require_aware(heartbeat_at)
        lease = self.heartbeat_lease(
            claimed.lease,
            lease_ttl_seconds=lease_ttl_seconds,
            checkpoint=checkpoint,
        )
        return ClaimedSession(recovery=claimed.recovery, lease=lease)

    def heartbeat_lease(
        self,
        lease: WorkerLease,
        *,
        lease_ttl_seconds: int,
        checkpoint: int | None = None,
    ) -> WorkerLease:
        ttl = self._ttl(lease_ttl_seconds)
        return self._lease_store.heartbeat(
            lease.session_id,
            fence=lease.fence,
            ttl=ttl,
            checkpoint=lease.checkpoint if checkpoint is None else checkpoint,
        )

    def release_claim(self, claimed: ClaimedSession) -> None:
        self.release_lease(claimed.lease)

    def release_lease(self, lease: WorkerLease) -> None:
        self._lease_store.release(lease.session_id, fence=lease.fence)

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
