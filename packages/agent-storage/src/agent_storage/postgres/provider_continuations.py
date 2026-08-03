"""Fenced PostgreSQL Provider Continuation aggregate and lifecycle reads."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_continuation import (
    CloudProviderContinuationArtifact,
    ProviderContinuationRef,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import (
    AdministrativeMutationCAS,
    WorkerMutationAuthority,
)
from agent_core.ports.provider_continuation_cloud import (
    CloudProviderContinuationCommitResult,
    CloudProviderContinuationStorePort,
    LoadedCloudProviderContinuation,
    ProviderContinuationSweepReceipt,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.provider_continuation_support import (
    artifact_from_row,
    assert_management_boundary,
    delete_hash,
    find_mutation,
    lock_expected_stream,
    replay_commit,
    request_hash,
    required_text,
    save_projections,
    scope_matches,
    sweep_hash,
    sweep_receipt,
    validate_selection_payload,
)


class PostgresProviderContinuationConflictError(ValueError):
    """Raised when a continuation request conflicts with durable authority."""


class PostgresProviderContinuationStore(CloudProviderContinuationStorePort):
    """Persist provider bytes and their canonical selection Event atomically."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        scope: OpaqueAuthorityScope,
    ) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._scope_key = scope.scope_key

    def commit_worker_selection(
        self,
        *,
        scope: OpaqueAuthorityScope,
        authority: WorkerMutationAuthority,
        continuation_id: str,
        session: Session,
        workspace: WorkspaceProjection,
        reference: ProviderContinuationRef,
        opaque_payload: bytes,
        maximum_ttl_seconds: int | None,
        selection_event: SessionEvent,
    ) -> CloudProviderContinuationCommitResult:
        continuation_id = required_text(continuation_id, "continuation_id")
        if not opaque_payload:
            raise ValueError("provider continuation payload must not be empty")
        if reference.expires_at is None:
            raise ValueError("cloud provider continuation requires an expiry")
        if maximum_ttl_seconds is not None:
            ttl = (reference.expires_at - reference.created_at).total_seconds()
            if ttl > maximum_ttl_seconds:
                raise ValueError("provider continuation exceeds capability TTL")
        self._validate_worker_request(scope, authority, selection_event, session, workspace)
        validate_selection_payload(
            selection_event,
            scope,
            continuation_id,
            reference,
            opaque_payload,
            PostgresProviderContinuationConflictError,
        )
        idempotency_key = selection_event.idempotency_key
        if idempotency_key is None:
            raise ValueError("cloud continuation selection requires an idempotency key")
        request_digest = request_hash(
            scope,
            continuation_id,
            session.session_id,
            reference,
            opaque_payload,
            maximum_ttl_seconds,
            selection_event,
        )
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            assert_current_lease_fence(
                connection,
                namespace,
                session.session_id,
                authority.lease_fence,
            )
            existing = connection.execute(
                """
                SELECT * FROM provider_continuation_artifacts
                WHERE deployment_namespace = %s AND session_id = %s
                  AND idempotency_key = %s
                FOR UPDATE
                """,
                (namespace, session.session_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                return replay_commit(
                    connection,
                    namespace,
                    existing,
                    request_digest,
                    PostgresProviderContinuationConflictError,
                )
            lock_expected_stream(
                connection,
                namespace,
                session.session_id,
                authority.expected_stream_revision,
                PostgresProviderContinuationConflictError,
            )
            connection.execute(
                """
                INSERT INTO provider_continuation_artifacts (
                    deployment_namespace, continuation_id, authority_issuer, namespace_id,
                    session_id, reference_id, provider, model_name, capability_version,
                    source_hash, opaque_payload, payload_sha256, size_bytes, created_at,
                    expires_at, lifecycle_revision, idempotency_key, request_hash,
                    accepted_lease_epoch, accepted_lease_fencing_token,
                    accepted_lease_owner_instance_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    0, %s, %s, %s, %s, %s
                )
                """,
                (
                    namespace,
                    continuation_id,
                    scope.authority_issuer,
                    scope.namespace_id,
                    session.session_id,
                    reference.reference_id,
                    reference.provider,
                    reference.model_name,
                    reference.capability_version,
                    reference.source_hash,
                    opaque_payload,
                    sha256(opaque_payload).hexdigest(),
                    len(opaque_payload),
                    reference.created_at,
                    reference.expires_at,
                    idempotency_key,
                    request_digest,
                    authority.lease_fence.control_plane_epoch,
                    authority.lease_fence.fencing_token,
                    authority.lease_fence.owner_instance_id,
                ),
            )
            canonical_event = append_event_in_transaction(connection, namespace, selection_event)
            if canonical_event.sequence != authority.expected_stream_revision + 1:
                raise PostgresProviderContinuationConflictError(
                    "continuation Event does not follow the expected stream revision"
                )
            stored_session, stored_workspace = save_projections(
                connection,
                namespace,
                canonical_event,
                session,
                workspace,
                PostgresProviderContinuationConflictError,
            )
            connection.execute(
                """
                UPDATE provider_continuation_artifacts
                SET selection_event_id = %s, selection_event_sequence = %s
                WHERE deployment_namespace = %s AND continuation_id = %s
                """,
                (
                    canonical_event.event_id,
                    canonical_event.sequence,
                    namespace,
                    continuation_id,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM provider_continuation_artifacts
                WHERE deployment_namespace = %s AND continuation_id = %s
                """,
                (namespace, continuation_id),
            ).fetchone()
            if row is None:
                raise PostgresProviderContinuationConflictError(
                    "continuation row disappeared before commit"
                )
        return CloudProviderContinuationCommitResult(
            artifact=artifact_from_row(row),
            event=canonical_event,
            session=stored_session,
            workspace=stored_workspace,
        )

    def load_compatible(
        self,
        continuation_id: str,
        *,
        scope: OpaqueAuthorityScope,
        session_id: SessionId,
        provider: str,
        model_name: str,
        capability_version: str,
        as_of: datetime | None = None,
    ) -> LoadedCloudProviderContinuation | None:
        if not scope_matches(scope, self._scope_key) or not scope.allows_session(session_id):
            return None
        effective_as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM provider_continuation_artifacts
                WHERE deployment_namespace = %s AND continuation_id = %s
                  AND authority_issuer = %s AND namespace_id = %s AND session_id = %s
                """,
                (
                    self._database.deployment_namespace,
                    continuation_id,
                    scope.authority_issuer,
                    scope.namespace_id,
                    session_id,
                ),
            ).fetchone()
        if row is None:
            return None
        artifact = artifact_from_row(row)
        if not artifact.is_compatible(
            scope=scope,
            session_id=session_id,
            provider=provider,
            model_name=model_name,
            capability_version=capability_version,
            as_of=effective_as_of,
        ):
            return None
        payload = row["opaque_payload"]
        if (
            not isinstance(payload, bytes)
            or len(payload) != artifact.size_bytes
            or sha256(payload).hexdigest() != artifact.payload_sha256
        ):
            raise ValueError("provider continuation payload failed integrity validation")
        return LoadedCloudProviderContinuation(artifact=artifact, opaque_payload=payload)

    def delete_for_worker(
        self,
        continuation_id: str,
        *,
        scope: OpaqueAuthorityScope,
        authority: WorkerMutationAuthority,
        idempotency_key: str,
        deleted_at: datetime | None = None,
    ) -> CloudProviderContinuationArtifact | None:
        continuation_id = required_text(continuation_id, "continuation_id")
        idempotency_key = required_text(idempotency_key, "idempotency_key")
        self._validate_scope(scope)
        if authority.deployment_namespace != self._database.deployment_namespace:
            raise LeaseLostError("continuation authority belongs to another namespace")
        if not scope.allows_session(authority.session_id):
            raise PostgresProviderContinuationConflictError(
                "continuation scope does not allow the Session"
            )
        with self._database.connect() as connection:
            assert_current_lease_fence(
                connection,
                self._database.deployment_namespace,
                authority.session_id,
                authority.lease_fence,
            )
            row = connection.execute(
                """
                SELECT * FROM provider_continuation_artifacts
                WHERE deployment_namespace = %s AND continuation_id = %s
                  AND authority_issuer = %s AND namespace_id = %s AND session_id = %s
                FOR UPDATE
                """,
                (
                    self._database.deployment_namespace,
                    continuation_id,
                    scope.authority_issuer,
                    scope.namespace_id,
                    authority.session_id,
                ),
            ).fetchone()
            if row is None:
                return None
            request_hash = delete_hash(scope, continuation_id, idempotency_key)
            mutation = find_mutation(connection, row, "delete", idempotency_key)
            if mutation is not None:
                if mutation["request_hash"] != request_hash:
                    raise PostgresProviderContinuationConflictError(
                        "delete idempotency key was reused with different meaning"
                    )
                return artifact_from_row(row)
            if row["deleted_at"] is None:
                timestamp = (deleted_at or datetime.now(UTC)).astimezone(UTC)
                connection.execute(
                    """
                    UPDATE provider_continuation_artifacts
                    SET opaque_payload = NULL, deleted_at = %s,
                        lifecycle_revision = lifecycle_revision + 1
                    WHERE deployment_namespace = %s AND continuation_id = %s
                    """,
                    (timestamp, self._database.deployment_namespace, continuation_id),
                )
            row = connection.execute(
                """
                SELECT * FROM provider_continuation_artifacts
                WHERE deployment_namespace = %s AND continuation_id = %s
                """,
                (self._database.deployment_namespace, continuation_id),
            ).fetchone()
            assert row is not None
            connection.execute(
                """
                INSERT INTO provider_continuation_mutations (
                    deployment_namespace, continuation_id, operation_kind,
                    idempotency_key, request_hash, resulting_revision
                ) VALUES (%s, %s, 'delete', %s, %s, %s)
                """,
                (
                    self._database.deployment_namespace,
                    continuation_id,
                    idempotency_key,
                    request_hash,
                    row["lifecycle_revision"],
                ),
            )
        return artifact_from_row(row)

    def sweep_expired(
        self,
        *,
        scope: OpaqueAuthorityScope,
        authority: AdministrativeMutationCAS,
        operation_id: UUID,
        operator_id: str,
        reason: str,
        limit: int = 100,
        as_of: datetime | None = None,
    ) -> ProviderContinuationSweepReceipt:
        self._validate_scope(scope)
        if not scope.is_full_namespace:
            raise PostgresProviderContinuationConflictError(
                "continuation sweep requires a full namespace scope"
            )
        if authority.deployment_namespace != self._database.deployment_namespace:
            raise PostgresProviderContinuationConflictError(
                "management CAS belongs to another namespace"
            )
        operator_id = required_text(operator_id, "operator_id")
        reason = required_text(reason, "reason")
        if not 1 <= limit <= 1000:
            raise ValueError("continuation sweep limit must be between 1 and 1000")
        effective_as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
        request_digest = sweep_hash(
            scope, operation_id, operator_id, reason, limit, as_of
        )
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            assert_management_boundary(
                connection,
                namespace,
                authority,
                PostgresProviderContinuationConflictError,
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"provider-continuation-sweep:{operation_id}",),
            )
            existing = connection.execute(
                """
                SELECT * FROM provider_continuation_management_audit
                WHERE operation_id = %s
                FOR UPDATE
                """,
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_digest:
                    raise PostgresProviderContinuationConflictError(
                        "management operation id was reused with different meaning"
                    )
                return sweep_receipt(existing, PostgresProviderContinuationConflictError)
            rows = connection.execute(
                """
                WITH expired AS (
                    SELECT continuation_id
                    FROM provider_continuation_artifacts
                    WHERE deployment_namespace = %s
                      AND authority_issuer = %s AND namespace_id = %s
                      AND deleted_at IS NULL AND expires_at <= %s
                    ORDER BY expires_at ASC, continuation_id ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE provider_continuation_artifacts AS artifact
                SET opaque_payload = NULL,
                    deleted_at = %s,
                    lifecycle_revision = lifecycle_revision + 1
                FROM expired
                WHERE artifact.deployment_namespace = %s
                  AND artifact.continuation_id = expired.continuation_id
                RETURNING artifact.continuation_id
                """,
                (
                    namespace,
                    scope.authority_issuer,
                    scope.namespace_id,
                    effective_as_of,
                    limit,
                    effective_as_of,
                    namespace,
                ),
            ).fetchall()
            expired_ids = tuple(str(row["continuation_id"]) for row in rows)
            audit_row = connection.execute(
                """
                INSERT INTO provider_continuation_management_audit (
                    operation_id, deployment_namespace, authority_issuer, namespace_id,
                    operator_id, reason, request_hash, expired_continuation_ids
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    operation_id,
                    namespace,
                    scope.authority_issuer,
                    scope.namespace_id,
                    operator_id,
                    reason,
                    request_digest,
                    Jsonb(list(expired_ids)),
                ),
            ).fetchone()
            assert audit_row is not None
        return sweep_receipt(audit_row, PostgresProviderContinuationConflictError)

    def _validate_scope(self, scope: OpaqueAuthorityScope) -> None:
        if not scope_matches(scope, self._scope_key):
            raise PostgresProviderContinuationConflictError(
                "continuation external authority does not match trusted composition"
            )

    def _validate_worker_request(
        self,
        scope: OpaqueAuthorityScope,
        authority: WorkerMutationAuthority,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
    ) -> None:
        self._validate_scope(scope)
        if authority.deployment_namespace != self._database.deployment_namespace:
            raise LeaseLostError("continuation authority belongs to another namespace")
        if authority.session_id != event.session_id or session.session_id != event.session_id:
            raise LeaseLostError("continuation authority belongs to another session")
        if workspace.session_id != event.session_id:
            raise PostgresProviderContinuationConflictError(
                "continuation Event and Workspace must share a Session"
            )
        if event.event_type is not EventType.CONTEXT_CONTINUATION_SELECTED:
            raise ValueError("cloud continuation aggregate requires a selection Event")
        if event.sequence != authority.expected_stream_revision + 1:
            raise PostgresProviderContinuationConflictError(
                "continuation Event does not target the next stream sequence"
            )
        if not scope.allows_session(event.session_id):
            raise PostgresProviderContinuationConflictError(
                "continuation scope does not allow the Session"
            )
