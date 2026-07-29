import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_storage import (
    HandoffStorageConflictError,
    SQLiteHandoffDispatchStore,
    SQLiteSessionHandoffStore,
)

NOW = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)


def test_worker_dispatch_reclaim_rotates_receipt_and_rejects_stale_ack(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    SQLiteSessionHandoffStore(database_path)
    child_session_id = SessionId(uuid4())
    _insert_pending_dispatch(database_path, child_session_id)
    dispatches = SQLiteHandoffDispatchStore(database_path)

    first = dispatches.claim_for_child(
        child_session_id,
        fence=_fence("worker-1", 1),
        claimed_at=NOW,
        lease_seconds=10,
    )
    assert first is not None and first.claim_token is not None
    reclaimed = dispatches.claim_for_child(
        child_session_id,
        fence=_fence("worker-2", 2),
        claimed_at=NOW + timedelta(seconds=11),
    )
    assert reclaimed is not None
    assert reclaimed.claim_token != first.claim_token

    with pytest.raises(HandoffStorageConflictError, match="not owned"):
        dispatches.acknowledge(first, checked_at=NOW + timedelta(seconds=11))

    dispatches.acknowledge(reclaimed, checked_at=NOW + timedelta(seconds=11))


def test_legacy_claimed_dispatch_is_requeued_during_incremental_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE handoff_dispatch_outbox (
                delivery_id TEXT PRIMARY KEY, child_session_id TEXT NOT NULL,
                handoff_id TEXT NOT NULL, status TEXT NOT NULL, claimed_by TEXT,
                claim_expires_at TEXT, created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO handoff_dispatch_outbox VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                "claimed",
                "legacy-worker",
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )

    SQLiteSessionHandoffStore(database_path)
    with sqlite3.connect(database_path) as connection:
        migrated = connection.execute(
            """
            SELECT status, claimed_by, claim_token, claim_epoch, claim_fencing_token,
                   claim_owner_instance_id, claim_expires_at
            FROM handoff_dispatch_outbox
            """
        ).fetchone()

    assert migrated == ("pending", None, None, None, None, None, None)


def _fence(worker_id: str, token: int) -> LeaseFence:
    return LeaseFence(
        control_plane_epoch=uuid4(), fencing_token=token, owner_instance_id=worker_id
    )


def _insert_pending_dispatch(database_path: Path, child_session_id: SessionId) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO handoff_dispatch_outbox (
                delivery_id, child_session_id, handoff_id, status, claimed_by, claim_token,
                claim_epoch, claim_fencing_token, claim_owner_instance_id, claim_expires_at,
                created_at
            ) VALUES (?, ?, ?, 'pending', NULL, NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (str(uuid4()), str(child_session_id), str(uuid4()), NOW.isoformat()),
        )
