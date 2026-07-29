"""Audited management recovery for cloud Artifact payload metadata."""

import hashlib
import json
from collections.abc import Callable
from typing import Any, TypeVar, cast

from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadRecord,
    CloudArtifactPayloadStateError,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactBeginPruneRequest,
    ArtifactCompensateRequest,
    ArtifactCompletePruneRequest,
    ArtifactFinalizeRequest,
    ArtifactManagementContext,
    ArtifactReconcileQuery,
)
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS
from pydantic import BaseModel

from agent_storage.postgres.artifact_payload_pruning import (
    begin_prune_after_boundary,
    complete_prune_after_boundary,
)
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import (
    assert_stream_revision,
    lock_payload,
)
from agent_storage.postgres.artifact_payload_worker_transitions import (
    compensate_after_boundary,
    finalize_after_boundary,
)
from agent_storage.postgres.database import PostgresDatabase

RequestT = TypeVar("RequestT", bound=BaseModel)


class ArtifactPayloadManagementMixin:
    """Keep management authority and audit separate from Worker fencing."""

    _database: PostgresDatabase

    def finalize_reconciled(
        self,
        request: ArtifactFinalizeRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord:
        return self._management_transition(
            request, authority, audit, "finalize", "staged", "finalized", finalize_after_boundary
        )

    def compensate_reconciled(
        self,
        request: ArtifactCompensateRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord:
        return self._management_transition(
            request,
            authority,
            audit,
            "compensate",
            "staged",
            "compensated",
            compensate_after_boundary,
        )

    def begin_retention_prune(
        self,
        request: ArtifactBeginPruneRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord:
        return self._management_transition(
            request,
            authority,
            audit,
            "begin_prune",
            "finalized",
            "pruning",
            begin_prune_after_boundary,
        )

    def complete_reconciled_prune(
        self,
        request: ArtifactCompletePruneRequest,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> CloudArtifactPayloadRecord:
        return self._management_transition(
            request,
            authority,
            audit,
            "complete_prune",
            "pruning",
            "pruned",
            complete_prune_after_boundary,
        )

    def list_reconcilable(
        self,
        query: ArtifactReconcileQuery,
        *,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
    ) -> tuple[CloudArtifactPayloadRecord, ...]:
        del audit  # validated management context; listing itself is read-only
        namespace = self._database.deployment_namespace
        _assert_management_scope(namespace, authority.session_id, authority)
        with self._database.connect() as connection:
            assert_stream_revision(
                connection,
                namespace,
                authority.session_id,
                authority.expected_stream_revision,
            )
            rows = connection.execute(
                """
                SELECT * FROM artifact_payload_metadata
                WHERE deployment_namespace = %s AND session_id = %s
                  AND lifecycle_status IN ('staged', 'pruning')
                  AND updated_at < %s
                ORDER BY updated_at, artifact_id
                LIMIT %s
                """,
                (namespace, authority.session_id, query.older_than, query.limit),
            ).fetchall()
        return tuple(artifact_payload_from_row(row) for row in rows)

    def _management_transition(
        self,
        request: RequestT,
        authority: AdministrativeMutationCAS,
        audit: ArtifactManagementContext,
        operation_kind: str,
        from_status: str,
        to_status: str,
        transition: Callable[[Any, str, RequestT], CloudArtifactPayloadRecord],
    ) -> CloudArtifactPayloadRecord:
        namespace = self._database.deployment_namespace
        session_id = cast(Any, request).session_id
        artifact_id = cast(Any, request).artifact_id
        _assert_management_scope(namespace, session_id, authority)
        request_hash = _management_hash(namespace, operation_kind, request, audit)
        with self._database.connect() as connection:
            assert_stream_revision(
                connection,
                namespace,
                session_id,
                authority.expected_stream_revision,
            )
            row = lock_payload(connection, namespace, artifact_id, session_id)
            replay = connection.execute(
                """
                SELECT artifact_id, operation_kind, request_hash
                FROM artifact_payload_management_audit
                WHERE deployment_namespace = %s AND operation_id = %s
                """,
                (namespace, audit.operation_id),
            ).fetchone()
            if replay is not None:
                if (
                    replay["artifact_id"] != artifact_id
                    or replay["operation_kind"] != operation_kind
                    or replay["request_hash"] != request_hash
                ):
                    raise CloudArtifactPayloadConflictError(
                        "management operation_id reused with different meaning"
                    )
                return artifact_payload_from_row(row)
            if row["lifecycle_status"] != from_status:
                raise CloudArtifactPayloadStateError(
                    f"management {operation_kind} requires {from_status} metadata"
                )
            result = transition(connection, namespace, request)
            connection.execute(
                """
                INSERT INTO artifact_payload_management_audit (
                    deployment_namespace, operation_id, artifact_id, operation_kind,
                    operator_id, reason, expected_stream_revision,
                    resulting_lifecycle_revision, from_status, to_status, request_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    namespace,
                    audit.operation_id,
                    artifact_id,
                    operation_kind,
                    audit.operator_id,
                    audit.reason,
                    authority.expected_stream_revision,
                    result.lifecycle_revision,
                    from_status,
                    to_status,
                    request_hash,
                ),
            )
            return result


def _assert_management_scope(
    namespace: str,
    session_id: Any,
    authority: AdministrativeMutationCAS,
) -> None:
    if authority.deployment_namespace != namespace or authority.session_id != session_id:
        raise CloudArtifactPayloadConflictError("management authority has the wrong scope")


def _management_hash(
    namespace: str,
    operation_kind: str,
    request: BaseModel,
    audit: ArtifactManagementContext,
) -> str:
    encoded = json.dumps(
        {
            "deployment_namespace": namespace,
            "operation_kind": operation_kind,
            "request": request.model_dump(mode="json"),
            "audit": audit.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
