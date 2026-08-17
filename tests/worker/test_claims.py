from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_storage import (
    LeaseConflictError,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_worker import SessionClaimService, SessionRecoveryError, SessionRecoveryService
from zebra_agent_worker.recovery import RecoveredSession


class ManualClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


CLAIMED_AT = datetime(2026, 6, 21, 23, 55, tzinfo=UTC)


def test_session_claim_service_claims_and_heartbeats_running_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    clock = ManualClock(CLAIMED_AT)
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path, clock=clock),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    claimed = claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=CLAIMED_AT,
        lease_ttl_seconds=30,
    )
    clock.now += timedelta(seconds=5)
    heartbeated = claim_service.heartbeat_claim(
        claimed,
        heartbeat_at=clock.now,
        lease_ttl_seconds=30,
        checkpoint=claimed.recovery.last_sequence + 1,
    )

    assert claimed.recovery.session.status.value == "running"
    assert claimed.lease.checkpoint == claimed.recovery.last_sequence
    assert heartbeated.lease.fence == claimed.lease.fence
    assert heartbeated.lease.checkpoint == claimed.recovery.last_sequence + 1


def test_session_claim_service_blocks_concurrent_worker_before_expiry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    clock = ManualClock(CLAIMED_AT)
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path, clock=clock),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=CLAIMED_AT,
        lease_ttl_seconds=30,
    )

    with pytest.raises(
        LeaseConflictError,
        match="active lease",
    ):
        claim_service.claim_session(
            session_id,
            worker_id="worker-b",
            claimed_at=CLAIMED_AT + timedelta(seconds=5),
            lease_ttl_seconds=30,
        )


def test_session_claim_service_allows_takeover_after_expiry(tmp_path: Path) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    clock = ManualClock(CLAIMED_AT)
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path, clock=clock),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    first = claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=CLAIMED_AT,
        lease_ttl_seconds=10,
    )
    clock.now += timedelta(seconds=11)
    claimed = claim_service.claim_session(
        session_id,
        worker_id="worker-b",
        claimed_at=clock.now,
        lease_ttl_seconds=30,
    )

    assert claimed.lease.worker_id == "worker-b"
    assert claimed.lease.fence.fencing_token == first.lease.fence.fencing_token + 1
    assert claimed.recovery.session.status.value == "running"


def test_session_claim_service_releases_claim(tmp_path: Path) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    lease_store = SQLiteLeaseStore(database_path, clock=ManualClock(CLAIMED_AT))
    claim_service = SessionClaimService(
        lease_store,
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    claimed = claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=CLAIMED_AT,
        lease_ttl_seconds=30,
    )

    claim_service.release_claim(claimed)

    assert lease_store.get(session_id) is None


def test_session_claim_acquires_before_recovery_and_releases_on_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "claim.db"
    missing_session = new_session_id()
    clock = ManualClock(CLAIMED_AT)
    lease_store = SQLiteLeaseStore(database_path, clock=clock)
    claim_service = SessionClaimService(
        lease_store,
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )

    with pytest.raises(SessionRecoveryError, match="missing session"):
        claim_service.claim_session(
            missing_session,
            worker_id="worker-a",
            claimed_at=CLAIMED_AT,
            lease_ttl_seconds=30,
        )

    assert lease_store.get(missing_session) is None
    replacement = lease_store.acquire(
        missing_session,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )
    assert replacement.fence.fencing_token == 2


def test_session_claim_does_not_return_if_lease_expires_during_recovery(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    clock = ManualClock(CLAIMED_AT)

    class SlowRecoveryService(SessionRecoveryService):
        def recover_session(
            self,
            requested_session_id: SessionId,
            *,
            worker_lease: WorkerLease | None = None,
        ) -> RecoveredSession:
            recovered = super().recover_session(
                requested_session_id,
                worker_lease=worker_lease,
            )
            clock.now += timedelta(seconds=31)
            return recovered

    lease_store = SQLiteLeaseStore(database_path, clock=clock)
    claim_service = SessionClaimService(
        lease_store,
        SlowRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )

    with pytest.raises(LeaseLostError, match="heartbeat rejected"):
        claim_service.claim_session(
            session_id,
            worker_id="worker-a",
            claimed_at=CLAIMED_AT,
            lease_ttl_seconds=30,
        )

    replacement = lease_store.acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )
    assert replacement.fence.fencing_token == 2


def test_session_claim_rejects_ttl_before_timedelta_overflow(tmp_path: Path) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path, clock=ManualClock(CLAIMED_AT)),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )

    with pytest.raises(ValueError, match="configured maximum"):
        claim_service.claim_session(
            session_id,
            worker_id="worker-a",
            claimed_at=CLAIMED_AT,
            lease_ttl_seconds=10**100,
        )


def _seed_running_session(database_path: Path) -> SessionId:
    event_store = SQLiteEventStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 21, 23, 50, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Claim Session"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Claim Session",
                "user_input": "continue",
                "workspace_root": str(Path("/tmp/claim-session")),
            },
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )
    return session_id
