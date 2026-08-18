"""Shared transaction checks for cloud Artifact lifecycle mutations."""

import hashlib
import json
from typing import Any, cast

from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadNotFoundError,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from pydantic import BaseModel

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.leases import assert_current_lease_fence


def assert_worker_boundary(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    authority: WorkerMutationAuthority,
) -> None:
    if authority.deployment_namespace != namespace or authority.session_id != session_id:
        raise LeaseLostError("artifact mutation authority has the wrong scope")
    assert_current_lease_fence(connection, namespace, session_id, authority.lease_fence)
    assert_stream_revision(
        connection,
        namespace,
        session_id,
        authority.expected_stream_revision,
    )


def assert_stream_revision(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    expected_revision: int,
) -> None:
    row = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        FOR SHARE
        """,
        (namespace, session_id),
    ).fetchone()
    if row is None or row["current_version"] != expected_revision:
        raise CloudArtifactPayloadConflictError("artifact mutation stream revision is stale")


def lock_payload(
    connection: Any,
    namespace: str,
    artifact_id: ArtifactId,
    session_id: SessionId,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT * FROM artifact_payload_metadata
        WHERE deployment_namespace = %s AND artifact_id = %s AND session_id = %s
        FOR UPDATE
        """,
        (namespace, artifact_id, session_id),
    ).fetchone()
    if row is None:
        raise CloudArtifactPayloadNotFoundError("artifact payload metadata not found")
    return cast("dict[str, Any]", row)


def mutation_replay(
    connection: Any,
    namespace: str,
    row: dict[str, Any],
    operation_kind: str,
    request: BaseModel,
) -> CloudArtifactPayloadRecord | None:
    idempotency_hash = hash_text(_idempotency_key(request))
    request_hash = mutation_request_hash(namespace, operation_kind, request)
    mutation = connection.execute(
        """
        SELECT request_hash FROM artifact_payload_mutations
        WHERE deployment_namespace = %s AND artifact_id = %s
          AND operation_kind = %s AND idempotency_key_hash = %s
        """,
        (namespace, row["artifact_id"], operation_kind, idempotency_hash),
    ).fetchone()
    if mutation is None:
        return None
    if mutation["request_hash"] != request_hash:
        raise CloudArtifactPayloadConflictError(
            "artifact mutation idempotency key reused with different meaning"
        )
    return artifact_payload_from_row(row)


def insert_mutation(
    connection: Any,
    namespace: str,
    artifact_id: ArtifactId,
    operation_kind: str,
    request: BaseModel,
    resulting_revision: int,
) -> None:
    connection.execute(
        """
        INSERT INTO artifact_payload_mutations (
            deployment_namespace, artifact_id, operation_kind,
            idempotency_key_hash, request_hash, resulting_revision
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            namespace,
            artifact_id,
            operation_kind,
            hash_text(_idempotency_key(request)),
            mutation_request_hash(namespace, operation_kind, request),
            resulting_revision,
        ),
    )


def require_expected_revision(row: dict[str, Any], expected_revision: int) -> None:
    if row["lifecycle_revision"] != expected_revision:
        raise CloudArtifactPayloadConflictError("artifact lifecycle revision is stale")


def require_matching_receipt(
    row: dict[str, Any],
    receipt: ArtifactObjectReceipt,
) -> None:
    expectation = receipt.expectation
    if (
        expectation.deployment_namespace != row["deployment_namespace"]
        or expectation.artifact_id != row["artifact_id"]
        or expectation.sha256 != row["sha256"]
        or expectation.size_bytes != row["size_bytes"]
        or row["object_version"] != receipt.object_version
        or row["object_verified_at"] != receipt.verified_at
    ):
        raise CloudArtifactPayloadConflictError(
            "object receipt does not match authoritative Artifact metadata"
        )


def mutation_request_hash(namespace: str, operation_kind: str, request: BaseModel) -> str:
    encoded = json.dumps(
        {
            "deployment_namespace": namespace,
            "operation_kind": operation_kind,
            "request": request.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _idempotency_key(request: BaseModel) -> str:
    return cast(str, request.model_dump()["idempotency_key"])
