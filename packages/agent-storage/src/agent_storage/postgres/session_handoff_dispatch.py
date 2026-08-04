"""Lease-fenced PostgreSQL Handoff delivery claims."""

from datetime import datetime, timedelta
from secrets import token_urlsafe
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import WorkspaceBindingRevision
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.handoff_dispatch_store import (
    FencedHandoffDispatchStorePort,
    HandoffDispatch,
)

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.session_handoff_facts import (
    read_source_facts_in_transaction,
)
from agent_storage.session_handoff_rows import HandoffStorageConflictError


class PostgresHandoffDispatchStore(FencedHandoffDispatchStorePort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def claim_for_child(
        self,
        child_session_id: SessionId,
        *,
        fence: LeaseFence | None = None,
        authority: WorkerMutationAuthority | None = None,
        operation_id: str | None = None,
        expected_stream_revision: int | None = None,
        expected_pointer_revision: int | None = None,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None:
        if claimed_at.tzinfo is None or lease_seconds <= 0:
            raise ValueError("dispatch claim requires positive lease and aware time")
        namespace = self._database.deployment_namespace
        fence = self._resolve_fence(
            namespace,
            child_session_id,
            fence=fence,
            authority=authority,
        )
        if operation_id is not None:
            _require_uuid(operation_id, "operation_id")
        claim_token = token_urlsafe(32)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT dispatch.delivery_id, dispatch.child_session_id,
                       dispatch.handoff_id, operation.operation_id,
                       stream.current_version AS stream_revision,
                       pointer.current_sequence AS pointer_revision,
                       dispatch.status, dispatch.claim_token, dispatch.claim_epoch,
                       dispatch.claim_fencing_token, dispatch.claim_owner_instance_id,
                       dispatch.claim_expires_at,
                       dispatch.claim_expires_at > transaction_timestamp() AS claim_active
                FROM handoff_dispatch_outbox AS dispatch
                JOIN handoff_operations AS operation
                  ON operation.deployment_namespace = dispatch.deployment_namespace
                 AND operation.handoff_id = dispatch.handoff_id
                 AND operation.target_session_id = dispatch.child_session_id
                JOIN session_streams AS stream
                  ON stream.deployment_namespace = dispatch.deployment_namespace
                 AND stream.session_id = dispatch.child_session_id
                JOIN session_projections AS pointer
                  ON pointer.deployment_namespace = dispatch.deployment_namespace
                 AND pointer.session_id = dispatch.child_session_id
                WHERE dispatch.deployment_namespace = %s
                  AND dispatch.child_session_id = %s
                  AND operation.status = 'committed'
                  AND dispatch.status IN ('pending', 'claimed')
                FOR UPDATE OF dispatch, operation, stream, pointer SKIP LOCKED
                """,
                (namespace, child_session_id),
            ).fetchone()
            if row is None:
                return None
            _validate_claim_expectations(
                row,
                operation_id=operation_id,
                expected_stream_revision=expected_stream_revision,
                expected_pointer_revision=expected_pointer_revision,
                authority=authority,
            )
            assert_current_lease_fence(connection, namespace, child_session_id, fence)
            canonical_authority = WorkerMutationAuthority(
                deployment_namespace=namespace,
                session_id=child_session_id,
                expected_stream_revision=int(row["stream_revision"]),
                lease_fence=fence,
            )
            if row["status"] == "claimed" and row["claim_active"]:
                if not _canonical_retry_requested(
                    authority=authority,
                    operation_id=operation_id,
                    expected_stream_revision=expected_stream_revision,
                    expected_pointer_revision=expected_pointer_revision,
                ):
                    return None
                assert_current_lease_fence(connection, namespace, child_session_id, fence)
                if not _claim_matches_fence(row, fence):
                    raise HandoffStorageConflictError(
                        "dispatch claim is owned by another worker"
                    )
                return self._dispatch_receipt(
                    row,
                    fence=fence,
                    claim_token=row["claim_token"],
                    claim_expires_at=row["claim_expires_at"],
                    authority=canonical_authority,
                )
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
        return self._dispatch_receipt(
            row,
            fence=fence,
            claim_token=claim_token,
            claim_expires_at=claimed["claim_expires_at"],
            authority=canonical_authority,
        )

    def acknowledge(self, claim: HandoffDispatch, *, checked_at: datetime) -> None:
        self._require_aware(checked_at)
        self._validate_receipt(claim)
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
        self._validate_receipt(claim)
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            current = read_source_facts_in_transaction(
                connection,
                namespace,
                claim.child_session_id,
                at=checked_at,
                lock_workspace=True,
                lock_stream=True,
            ).workspace_revision
            if current != expected:
                return current
            if self._acknowledge(connection, claim) != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")
            return current

    def _acknowledge(self, connection: Any, claim: HandoffDispatch) -> int:
        namespace = self._database.deployment_namespace
        fence = claim.claim_fence
        assert fence is not None
        row = connection.execute(
            """
            SELECT dispatch.status, dispatch.claim_token, dispatch.claim_epoch,
                   dispatch.claim_fencing_token, dispatch.claim_owner_instance_id,
                   dispatch.claim_expires_at, dispatch.acked_at,
                   dispatch.child_session_id, operation.operation_id,
                   operation.status AS operation_status,
                   stream.current_version AS stream_revision,
                   pointer.current_sequence AS pointer_revision
            FROM handoff_dispatch_outbox AS dispatch
            JOIN handoff_operations AS operation
              ON operation.deployment_namespace = dispatch.deployment_namespace
             AND operation.handoff_id = dispatch.handoff_id
             AND operation.target_session_id = dispatch.child_session_id
            JOIN session_streams AS stream
              ON stream.deployment_namespace = dispatch.deployment_namespace
             AND stream.session_id = dispatch.child_session_id
            JOIN session_projections AS pointer
              ON pointer.deployment_namespace = dispatch.deployment_namespace
             AND pointer.session_id = dispatch.child_session_id
            WHERE dispatch.deployment_namespace = %s
              AND dispatch.delivery_id = %s
            FOR UPDATE OF dispatch, operation, stream, pointer
            """,
            (namespace, claim.delivery_id),
        ).fetchone()
        if row is None or row["child_session_id"] != claim.child_session_id:
            return 0
        if (
            row["operation_status"] != "committed"
            or str(row["operation_id"]) != claim.operation_id
            or int(row["stream_revision"]) != claim.expected_stream_revision
            or int(row["pointer_revision"]) != claim.expected_pointer_revision
        ):
            return 0
        assert_current_lease_fence(
            connection,
            namespace,
            claim.child_session_id,
            fence,
        )
        if row["status"] == "acked":
            # v8 clears the token on ACK. The expiry boundary distinguishes a
            # replay of this generation from a receipt reclaimed before it.
            if row["acked_at"] is None or claim.claim_expires_at <= row["acked_at"]:
                return 0
            return 1
        if row["status"] != "claimed":
            return 0
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

    def _resolve_fence(
        self,
        namespace: str,
        child_session_id: SessionId,
        *,
        fence: LeaseFence | None,
        authority: WorkerMutationAuthority | None,
    ) -> LeaseFence:
        if authority is not None:
            if (
                authority.deployment_namespace != namespace
                or authority.session_id != child_session_id
            ):
                raise HandoffStorageConflictError(
                    "dispatch authority namespace or session does not match"
                )
            if fence is not None and fence != authority.lease_fence:
                raise HandoffStorageConflictError("dispatch fence does not match authority")
            return authority.lease_fence
        if fence is None:
            raise HandoffStorageConflictError("dispatch claim requires WorkerMutationAuthority")
        return fence

    @staticmethod
    def _dispatch_receipt(
        row: dict[str, Any],
        *,
        fence: LeaseFence,
        claim_token: str,
        claim_expires_at: datetime,
        authority: WorkerMutationAuthority,
    ) -> HandoffDispatch:
        return HandoffDispatch(
            delivery_id=str(row["delivery_id"]),
            child_session_id=SessionId(row["child_session_id"]),
            handoff_id=HandoffId(row["handoff_id"]),
            status="claimed",
            claimed_by=fence.owner_instance_id,
            claim_token=claim_token,
            claim_fence=fence,
            claim_expires_at=claim_expires_at,
            operation_id=str(row["operation_id"]),
            expected_stream_revision=int(row["stream_revision"]),
            expected_pointer_revision=int(row["pointer_revision"]),
            authority=authority,
        )

    def _validate_receipt(self, claim: HandoffDispatch) -> None:
        if (
            claim.claim_token is None
            or claim.claim_fence is None
            or claim.claim_expires_at is None
            or claim.operation_id is None
            or claim.expected_stream_revision is None
            or claim.expected_pointer_revision is None
            or claim.authority is None
        ):
            raise HandoffStorageConflictError("dispatch claim receipt is incomplete")
        namespace = self._database.deployment_namespace
        if (
            claim.authority.deployment_namespace != namespace
            or claim.authority.session_id != claim.child_session_id
            or claim.authority.lease_fence != claim.claim_fence
            or claim.authority.expected_stream_revision != claim.expected_stream_revision
        ):
            raise HandoffStorageConflictError("dispatch claim authority does not match receipt")
        _require_uuid(claim.operation_id, "operation_id")

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("dispatch acknowledgment requires aware time")


def _validate_claim_expectations(
    row: dict[str, Any],
    *,
    operation_id: str | None,
    expected_stream_revision: int | None,
    expected_pointer_revision: int | None,
    authority: WorkerMutationAuthority | None,
) -> None:
    if operation_id is not None and str(row["operation_id"]) != operation_id:
        raise HandoffStorageConflictError("dispatch operation identity changed")
    stream_revision = int(row["stream_revision"])
    pointer_revision = int(row["pointer_revision"])
    if expected_stream_revision is not None and expected_stream_revision != stream_revision:
        raise HandoffStorageConflictError("dispatch stream revision changed")
    if expected_pointer_revision is not None and expected_pointer_revision != pointer_revision:
        raise HandoffStorageConflictError("dispatch pointer revision changed")
    if authority is not None and authority.expected_stream_revision != stream_revision:
        raise HandoffStorageConflictError("dispatch authority stream revision changed")


def _canonical_retry_requested(
    *,
    authority: WorkerMutationAuthority | None,
    operation_id: str | None,
    expected_stream_revision: int | None,
    expected_pointer_revision: int | None,
) -> bool:
    return any(
        value is not None
        for value in (
            authority,
            operation_id,
            expected_stream_revision,
            expected_pointer_revision,
        )
    )


def _claim_matches_fence(row: dict[str, Any], fence: LeaseFence) -> bool:
    return bool(
        row["claim_epoch"] == fence.control_plane_epoch
        and row["claim_fencing_token"] == fence.fencing_token
        and row["claim_owner_instance_id"] == fence.owner_instance_id
    )


def _require_uuid(value: str, field_name: str) -> None:
    try:
        UUID(str(value))
    except (TypeError, ValueError) as error:
        raise HandoffStorageConflictError(f"{field_name} must be a UUID") from error
