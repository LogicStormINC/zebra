from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_storage import (
    LeaseConflictError,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
)
from zebra_agent_worker import SessionClaimService, SessionRecoveryService


def test_session_claim_service_claims_and_heartbeats_running_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
        ),
    )
    claimed_at = datetime(2026, 6, 21, 23, 55, tzinfo=UTC)

    claimed = claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=claimed_at,
        lease_ttl_seconds=30,
    )
    heartbeated = claim_service.heartbeat_claim(
        claimed,
        heartbeat_at=claimed_at + timedelta(seconds=5),
        lease_ttl_seconds=30,
        checkpoint=claimed.recovery.last_sequence + 1,
    )

    assert claimed.recovery.session.status.value == "running"
    assert claimed.lease.checkpoint == claimed.recovery.last_sequence
    assert heartbeated.lease.checkpoint == claimed.recovery.last_sequence + 1


def test_session_claim_service_blocks_concurrent_worker_before_expiry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
        ),
    )
    claimed_at = datetime(2026, 6, 21, 23, 56, tzinfo=UTC)
    claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=claimed_at,
        lease_ttl_seconds=30,
    )

    with pytest.raises(
        LeaseConflictError,
        match="session already leased by another worker",
    ):
        claim_service.claim_session(
            session_id,
            worker_id="worker-b",
            claimed_at=claimed_at + timedelta(seconds=5),
            lease_ttl_seconds=30,
        )


def test_session_claim_service_allows_takeover_after_expiry(tmp_path: Path) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
        ),
    )
    claimed_at = datetime(2026, 6, 21, 23, 57, tzinfo=UTC)
    claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=claimed_at,
        lease_ttl_seconds=10,
    )

    claimed = claim_service.claim_session(
        session_id,
        worker_id="worker-b",
        claimed_at=claimed_at + timedelta(seconds=11),
        lease_ttl_seconds=30,
    )

    assert claimed.lease.worker_id == "worker-b"
    assert claimed.recovery.session.status.value == "running"


def test_session_claim_service_releases_claim(tmp_path: Path) -> None:
    database_path = tmp_path / "claim.db"
    session_id = _seed_running_session(database_path)
    lease_store = SQLiteLeaseStore(database_path)
    claim_service = SessionClaimService(
        lease_store,
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
        ),
    )
    claimed_at = datetime(2026, 6, 21, 23, 58, tzinfo=UTC)
    claimed = claim_service.claim_session(
        session_id,
        worker_id="worker-a",
        claimed_at=claimed_at,
        lease_ttl_seconds=30,
    )

    claim_service.release_claim(claimed)

    assert lease_store.get(session_id) is None


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
            payload={"title": "Claim Session", "user_input": "continue"},
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
