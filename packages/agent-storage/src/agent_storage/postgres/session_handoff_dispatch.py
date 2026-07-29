"""Lease-fenced PostgreSQL Handoff delivery claims."""

from datetime import datetime, timedelta
from secrets import token_urlsafe
from typing import Any

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import WorkspaceBindingRevision
from agent_core.ports.handoff_dispatch_store import (
    HandoffDispatch,
    HandoffDispatchStorePort,
)

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.session_handoff_facts import (
    read_source_facts_in_transaction,
)
from agent_storage.session_handoff_rows import HandoffStorageConflictError


class PostgresHandoffDispatchStore(HandoffDispatchStorePort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

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
        namespace = self._database.deployment_namespace
        claim_token = token_urlsafe(32)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT delivery_id FROM handoff_dispatch_outbox
                WHERE deployment_namespace = %s AND child_session_id = %s
                  AND (status = 'pending' OR (
                      status = 'claimed' AND claim_expires_at <= transaction_timestamp()
                  ))
                FOR UPDATE SKIP LOCKED
                """,
                (namespace, child_session_id),
            ).fetchone()
            if row is None:
                return None
            assert_current_lease_fence(connection, namespace, child_session_id, fence)
            claimed = connection.execute(
                """
                UPDATE handoff_dispatch_outbox
                SET status = 'claimed', claim_token = %s, claim_epoch = %s,
                    claim_fencing_token = %s, claim_owner_instance_id = %s,
                    claim_expires_at = transaction_timestamp() + %s::interval,
                    acked_at = NULL
                WHERE deployment_namespace = %s AND delivery_id = %s
                RETURNING delivery_id, child_session_id, handoff_id,
                          claim_expires_at
                """,
                (
                    claim_token,
                    fence.control_plane_epoch,
                    fence.fencing_token,
                    fence.owner_instance_id,
                    timedelta(seconds=lease_seconds),
                    namespace,
                    row["delivery_id"],
                ),
            ).fetchone()
            assert claimed is not None
        return HandoffDispatch(
            delivery_id=str(claimed["delivery_id"]),
            child_session_id=SessionId(claimed["child_session_id"]),
            handoff_id=HandoffId(claimed["handoff_id"]),
            status="claimed",
            claimed_by=fence.owner_instance_id,
            claim_token=claim_token,
            claim_fence=fence,
            claim_expires_at=claimed["claim_expires_at"],
        )

    def acknowledge(self, claim: HandoffDispatch, *, checked_at: datetime) -> None:
        self._require_aware(checked_at)
        with self._database.connect() as connection:
            if self._acknowledge(connection, claim) != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")

    def acknowledge_if_workspace_matches(
        self,
        claim: HandoffDispatch,
        *,
        expected: WorkspaceBindingRevision,
        checked_at: datetime,
    ) -> WorkspaceBindingRevision:
        self._require_aware(checked_at)
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            current = read_source_facts_in_transaction(
                connection,
                namespace,
                claim.child_session_id,
                at=checked_at,
                lock_workspace=True,
            ).workspace_revision
            if current != expected:
                return current
            if self._acknowledge(connection, claim) != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")
            return current

    def _acknowledge(self, connection: Any, claim: HandoffDispatch) -> int:
        if (
            claim.claim_token is None
            or claim.claim_fence is None
            or claim.claim_expires_at is None
        ):
            raise HandoffStorageConflictError("dispatch claim receipt is incomplete")
        namespace = self._database.deployment_namespace
        fence = claim.claim_fence
        assert_current_lease_fence(
            connection,
            namespace,
            claim.child_session_id,
            fence,
        )
        result = connection.execute(
            """
            UPDATE handoff_dispatch_outbox
            SET status = 'acked', claim_token = NULL, claim_epoch = NULL,
                claim_fencing_token = NULL, claim_owner_instance_id = NULL,
                claim_expires_at = NULL, acked_at = transaction_timestamp()
            WHERE deployment_namespace = %s AND delivery_id = %s
              AND child_session_id = %s AND status = 'claimed'
              AND claim_token = %s AND claim_epoch = %s
              AND claim_fencing_token = %s AND claim_owner_instance_id = %s
              AND claim_expires_at = %s
              AND claim_expires_at > transaction_timestamp()
            """,
            (
                namespace,
                claim.delivery_id,
                claim.child_session_id,
                claim.claim_token,
                fence.control_plane_epoch,
                fence.fencing_token,
                fence.owner_instance_id,
                claim.claim_expires_at,
            ),
        )
        return int(result.rowcount)

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("dispatch acknowledgment requires aware time")
