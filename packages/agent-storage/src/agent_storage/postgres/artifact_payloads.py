"""Fenced PostgreSQL authority for cloud Artifact payload metadata."""

from hashlib import sha256
from typing import Any, cast

from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactBeginPruneRequest,
    ArtifactCompensateRequest,
    ArtifactCompletePruneRequest,
    ArtifactFinalizeRequest,
    ArtifactMetadataQuery,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
    canonical_artifact_reserve_hash,
)
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from psycopg import errors

from agent_storage.postgres.artifact_payload_pruning import begin_prune, complete_prune
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_worker_transitions import (
    compensate,
    finalize,
    record_object,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence


class PostgresCloudArtifactPayloadStore:
    """Persist cloud payload lifecycle facts without performing object I/O."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def reserve_for_worker(
        self,
        request: ArtifactReserveRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord:
        namespace = self._database.deployment_namespace
        self._validate_worker_authority(request, authority)
        request_hash = canonical_artifact_reserve_hash(namespace, request)
        idempotency_hash = _hash_text(request.idempotency_key)
        try:
            with self._database.connect() as connection:
                assert_current_lease_fence(
                    connection,
                    namespace,
                    request.session_id,
                    authority.lease_fence,
                )
                replay = _find_reservation(
                    connection,
                    namespace,
                    request.session_id,
                    idempotency_hash,
                    lock=True,
                )
                if replay is not None:
                    return _require_same_reservation(replay, request_hash)
                _assert_stream_revision(
                    connection,
                    namespace,
                    request.session_id,
                    authority.expected_stream_revision,
                )
                row = connection.execute(
                    """
                    INSERT INTO artifact_payload_metadata (
                        deployment_namespace, artifact_id, session_id,
                        intended_event_sequence, expected_stream_revision,
                        kind, mime_type, sha256, size_bytes,
                        idempotency_key, idempotency_key_hash, request_hash,
                        file_name, retained_until,
                        reservation_epoch, reservation_fencing_token,
                        reservation_owner_instance_id,
                        lifecycle_status, lifecycle_revision, request_created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, 'staged', 0, %s
                    )
                    ON CONFLICT (
                        deployment_namespace, session_id, idempotency_key_hash
                    ) DO NOTHING
                    RETURNING *
                    """,
                    (
                        namespace,
                        request.artifact_id,
                        request.session_id,
                        request.intended_event_sequence,
                        authority.expected_stream_revision,
                        request.kind,
                        request.mime_type,
                        request.sha256,
                        request.size_bytes,
                        request.idempotency_key,
                        idempotency_hash,
                        request_hash,
                        request.file_name,
                        request.retained_until,
                        authority.lease_fence.control_plane_epoch,
                        authority.lease_fence.fencing_token,
                        authority.lease_fence.owner_instance_id,
                        request.created_at,
                    ),
                ).fetchone()
                if row is not None:
                    return artifact_payload_from_row(row)
                replay = _find_reservation(
                    connection,
                    namespace,
                    request.session_id,
                    idempotency_hash,
                    lock=True,
                )
                assert replay is not None
                return _require_same_reservation(replay, request_hash)
        except CloudArtifactPayloadConflictError:
            raise
        except errors.IntegrityError as error:
            raise CloudArtifactPayloadConflictError(
                "artifact reservation conflicts with authoritative metadata"
            ) from error

    def get_metadata(
        self,
        query: ArtifactMetadataQuery,
    ) -> CloudArtifactPayloadRecord | None:
        if query.deployment_namespace != self._database.deployment_namespace:
            return None
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM artifact_payload_metadata
                WHERE deployment_namespace = %s AND artifact_id = %s
                  AND session_id = %s
                """,
                (
                    query.deployment_namespace,
                    query.artifact_id,
                    query.session_id,
                ),
            ).fetchone()
        return None if row is None else artifact_payload_from_row(row)

    def record_object_for_worker(
        self,
        request: ArtifactRecordObjectRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord:
        with self._database.connect() as connection:
            return record_object(
                connection,
                self._database.deployment_namespace,
                request,
                authority,
            )

    def finalize_for_worker(
        self,
        request: ArtifactFinalizeRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord:
        with self._database.connect() as connection:
            return finalize(
                connection,
                self._database.deployment_namespace,
                request,
                authority,
            )

    def compensate_for_worker(
        self,
        request: ArtifactCompensateRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord:
        with self._database.connect() as connection:
            return compensate(
                connection,
                self._database.deployment_namespace,
                request,
                authority,
            )

    def begin_prune_for_worker(
        self,
        request: ArtifactBeginPruneRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord:
        with self._database.connect() as connection:
            return begin_prune(
                connection,
                self._database.deployment_namespace,
                request,
                authority,
            )

    def complete_prune_for_worker(
        self,
        request: ArtifactCompletePruneRequest,
        *,
        authority: WorkerMutationAuthority,
    ) -> CloudArtifactPayloadRecord:
        with self._database.connect() as connection:
            return complete_prune(
                connection,
                self._database.deployment_namespace,
                request,
                authority,
            )

    def _validate_worker_authority(
        self,
        request: ArtifactReserveRequest,
        authority: WorkerMutationAuthority,
    ) -> None:
        if authority.deployment_namespace != self._database.deployment_namespace:
            raise LeaseLostError("artifact authority belongs to another namespace")
        if authority.session_id != request.session_id:
            raise LeaseLostError("artifact authority belongs to another session")
        if request.intended_event_sequence != authority.expected_stream_revision + 1:
            raise CloudArtifactPayloadConflictError(
                "artifact reservation does not target the next canonical Event"
            )


def _find_reservation(
    connection: Any,
    namespace: str,
    session_id: object,
    idempotency_hash: str,
    *,
    lock: bool,
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = connection.execute(
        """
        SELECT * FROM artifact_payload_metadata
        WHERE deployment_namespace = %s AND session_id = %s
          AND idempotency_key_hash = %s
        """
        + suffix,
        (namespace, session_id, idempotency_hash),
    ).fetchone()
    return cast("dict[str, Any] | None", row)


def _require_same_reservation(
    row: dict[str, Any],
    request_hash: str,
) -> CloudArtifactPayloadRecord:
    if row["request_hash"] != request_hash:
        raise CloudArtifactPayloadConflictError(
            "artifact idempotency key reused with a different reservation"
        )
    return artifact_payload_from_row(row)


def _assert_stream_revision(
    connection: Any,
    namespace: str,
    session_id: object,
    expected_revision: int,
) -> None:
    row = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        FOR UPDATE
        """,
        (namespace, session_id),
    ).fetchone()
    if row is None or row["current_version"] != expected_revision:
        raise CloudArtifactPayloadConflictError(
            "artifact reservation stream revision is stale"
        )


def _hash_text(value: str) -> str:
    return sha256(value.encode()).hexdigest()
