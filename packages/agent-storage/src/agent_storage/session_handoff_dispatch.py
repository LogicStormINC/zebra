from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import WorkspaceBindingRevision
from agent_core.ports.handoff_dispatch_store import (
    HandoffDispatch,
    HandoffDispatchStorePort,
)

from agent_storage.database import SQLiteDatabase
from agent_storage.session_handoff_facts import read_source_facts
from agent_storage.session_handoff_rows import HandoffStorageConflictError


class SQLiteHandoffDispatchStore(HandoffDispatchStorePort):
    """Claims the handoff delivery for a specific child selected by the worker."""

    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)

    def claim_for_child(
        self,
        child_session_id: SessionId,
        *,
        fence: LeaseFence,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None:
        if claimed_at.tzinfo is None or lease_seconds <= 0:
            raise ValueError("dispatch claim requires positive lease and aware time")
        expires_at = claimed_at + timedelta(seconds=lease_seconds)
        claim_token = token_urlsafe(32)
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
            if not self._has_current_lease(connection, child_session_id, fence, at=claimed_at):
                raise HandoffStorageConflictError("dispatch claim fence is not the current lease")
            connection.execute(
                """
                UPDATE handoff_dispatch_outbox
                SET status = 'claimed', claimed_by = ?, claim_token = ?, claim_epoch = ?,
                    claim_fencing_token = ?, claim_owner_instance_id = ?, claim_expires_at = ?
                WHERE delivery_id = ?
                """,
                (
                    fence.owner_instance_id,
                    claim_token,
                    str(fence.control_plane_epoch),
                    fence.fencing_token,
                    fence.owner_instance_id,
                    expires_at.isoformat(),
                    row["delivery_id"],
                ),
            )
        return HandoffDispatch(
            delivery_id=row["delivery_id"],
            child_session_id=SessionId(UUID(row["child_session_id"])),
            handoff_id=HandoffId(UUID(row["handoff_id"])),
            status="claimed",
            claimed_by=fence.owner_instance_id,
            claim_token=claim_token,
            claim_fence=fence,
            claim_expires_at=expires_at,
        )

    def acknowledge(self, claim: HandoffDispatch, *, checked_at: datetime) -> None:
        if checked_at.tzinfo is None:
            raise ValueError("dispatch acknowledgment requires aware time")
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._acknowledge(connection, claim, checked_at=checked_at) != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")

    def acknowledge_if_workspace_matches(
        self,
        claim: HandoffDispatch,
        *,
        expected: WorkspaceBindingRevision,
        checked_at: datetime,
    ) -> WorkspaceBindingRevision:
        """CAS-check inherited workspace facts in the same transaction as the ack."""
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = read_source_facts(connection, claim.child_session_id, at=checked_at)
            if current.workspace_revision != expected:
                return current.workspace_revision
            if self._acknowledge(connection, claim, checked_at=checked_at) != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")
            return current.workspace_revision

    @staticmethod
    def _acknowledge(
        connection: sqlite3.Connection,
        claim: HandoffDispatch,
        *,
        checked_at: datetime,
    ) -> int:
        if claim.claim_token is None or claim.claim_fence is None:
            raise HandoffStorageConflictError("dispatch claim receipt is incomplete")
        fence = claim.claim_fence
        cursor = connection.execute(
            """
            UPDATE handoff_dispatch_outbox
            SET status = 'acked', claimed_by = NULL, claim_token = NULL, claim_epoch = NULL,
                claim_fencing_token = NULL, claim_owner_instance_id = NULL,
                claim_expires_at = NULL
            WHERE delivery_id = ? AND child_session_id = ? AND status = 'claimed'
              AND claim_token = ? AND claim_epoch = ? AND claim_fencing_token = ?
              AND claim_owner_instance_id = ? AND claim_expires_at > ?
              AND EXISTS (
                  SELECT 1 FROM worker_leases
                  WHERE session_id = ? AND control_plane_epoch = ?
                    AND control_plane_epoch = (
                        SELECT epoch FROM control_plane_epochs
                        WHERE deployment_namespace = 'local'
                    )
                    AND fencing_token = ? AND worker_id = ? AND released_at IS NULL
                    AND julianday(expires_at) > julianday(?)
              )
            """,
            (
                claim.delivery_id,
                str(claim.child_session_id),
                claim.claim_token,
                str(fence.control_plane_epoch),
                fence.fencing_token,
                fence.owner_instance_id,
                checked_at.isoformat(),
                str(claim.child_session_id),
                str(fence.control_plane_epoch),
                fence.fencing_token,
                fence.owner_instance_id,
                checked_at.isoformat(),
            ),
        )
        return cursor.rowcount

    @staticmethod
    def _has_current_lease(
        connection: sqlite3.Connection,
        child_session_id: SessionId,
        fence: LeaseFence,
        *,
        at: datetime,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1 FROM worker_leases
            WHERE session_id = ? AND control_plane_epoch = ?
              AND control_plane_epoch = (
                  SELECT epoch FROM control_plane_epochs WHERE deployment_namespace = 'local'
              )
              AND fencing_token = ? AND worker_id = ? AND released_at IS NULL
              AND julianday(expires_at) > julianday(?)
            """,
            (
                str(child_session_id),
                str(fence.control_plane_epoch),
                fence.fencing_token,
                fence.owner_instance_id,
                at.isoformat(),
            ),
        ).fetchone()
        return row is not None
