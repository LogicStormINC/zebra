from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.session_handoff import WorkspaceBindingRevision

from agent_storage.database import SQLiteDatabase
from agent_storage.session_handoff_facts import read_source_facts
from agent_storage.session_handoff_rows import HandoffDispatch, HandoffStorageConflictError


class SQLiteHandoffDispatchStore:
    """Claims the handoff delivery for a specific child selected by the worker."""

    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)

    def claim_for_child(
        self,
        child_session_id: SessionId,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None:
        if not worker_id.strip() or claimed_at.tzinfo is None or lease_seconds <= 0:
            raise ValueError("dispatch claim requires worker, positive lease and aware time")
        expires_at = claimed_at + timedelta(seconds=lease_seconds)
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM handoff_dispatch_outbox
                WHERE child_session_id = ? AND (
                    status = 'pending' OR
                    (status = 'claimed' AND claim_expires_at <= ?)
                )
                """,
                (str(child_session_id), claimed_at.isoformat()),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE handoff_dispatch_outbox
                SET status = 'claimed', claimed_by = ?, claim_expires_at = ?
                WHERE delivery_id = ?
                """,
                (worker_id, expires_at.isoformat(), row["delivery_id"]),
            )
        return HandoffDispatch(
            delivery_id=row["delivery_id"],
            child_session_id=SessionId(UUID(row["child_session_id"])),
            handoff_id=HandoffId(UUID(row["handoff_id"])),
            status="claimed",
            claimed_by=worker_id,
            claim_expires_at=expires_at,
        )

    def acknowledge(self, delivery_id: str, *, worker_id: str) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE handoff_dispatch_outbox SET status = 'acked', claim_expires_at = NULL
                WHERE delivery_id = ? AND status = 'claimed' AND claimed_by = ?
                """,
                (delivery_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")

    def acknowledge_if_workspace_matches(
        self,
        delivery_id: str,
        *,
        child_session_id: SessionId,
        worker_id: str,
        expected: WorkspaceBindingRevision,
        checked_at: datetime,
    ) -> WorkspaceBindingRevision:
        """CAS-check inherited workspace facts in the same transaction as the ack."""
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = read_source_facts(connection, child_session_id, at=checked_at)
            if current.workspace_revision != expected:
                return current.workspace_revision
            cursor = connection.execute(
                """
                UPDATE handoff_dispatch_outbox SET status = 'acked', claim_expires_at = NULL
                WHERE delivery_id = ? AND status = 'claimed' AND claimed_by = ?
                """,
                (delivery_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")
            return current.workspace_revision
