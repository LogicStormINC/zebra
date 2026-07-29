"""Worker-owned cloud Artifact lifecycle transitions."""

from typing import Any

from agent_core.domain.artifact_objects import ArtifactObjectVerificationStatus
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadRecord,
    CloudArtifactPayloadStateError,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactCompensateRequest,
    ArtifactFinalizeRequest,
    ArtifactRecordObjectRequest,
)
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import (
    assert_worker_boundary,
    insert_mutation,
    lock_payload,
    mutation_replay,
    require_expected_revision,
    require_matching_receipt,
)


def record_object(
    connection: Any,
    namespace: str,
    request: ArtifactRecordObjectRequest,
    authority: WorkerMutationAuthority,
) -> CloudArtifactPayloadRecord:
    assert_worker_boundary(connection, namespace, request.session_id, authority)
    row = lock_payload(connection, namespace, request.artifact_id, request.session_id)
    replay = mutation_replay(connection, namespace, row, "record_object", request)
    if replay is not None:
        return replay
    require_expected_revision(row, request.expected_lifecycle_revision)
    if row["lifecycle_status"] != "staged" or row["object_version"] is not None:
        raise CloudArtifactPayloadStateError("only an unrecorded staged Artifact accepts bytes")
    receipt = request.object_receipt
    expectation = receipt.expectation
    if (
        expectation.deployment_namespace != namespace
        or expectation.artifact_id != request.artifact_id
        or expectation.sha256 != row["sha256"]
        or expectation.size_bytes != row["size_bytes"]
    ):
        raise CloudArtifactPayloadConflictError("object receipt does not match reservation")
    revision = row["lifecycle_revision"] + 1
    updated = connection.execute(
        """
        UPDATE artifact_payload_metadata
        SET object_version = %s, object_verified_at = %s,
            lifecycle_revision = %s, updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND artifact_id = %s
        RETURNING *
        """,
        (
            receipt.object_version,
            receipt.verified_at,
            revision,
            namespace,
            request.artifact_id,
        ),
    ).fetchone()
    assert updated is not None
    insert_mutation(connection, namespace, request.artifact_id, "record_object", request, revision)
    return artifact_payload_from_row(updated)


def finalize(
    connection: Any,
    namespace: str,
    request: ArtifactFinalizeRequest,
    authority: WorkerMutationAuthority,
) -> CloudArtifactPayloadRecord:
    assert_worker_boundary(connection, namespace, request.session_id, authority)
    return finalize_after_boundary(connection, namespace, request)


def finalize_after_boundary(
    connection: Any,
    namespace: str,
    request: ArtifactFinalizeRequest,
) -> CloudArtifactPayloadRecord:
    row = lock_payload(connection, namespace, request.artifact_id, request.session_id)
    replay = mutation_replay(connection, namespace, row, "finalize", request)
    if replay is not None:
        return replay
    require_expected_revision(row, request.expected_lifecycle_revision)
    if row["lifecycle_status"] != "staged" or row["object_version"] is None:
        raise CloudArtifactPayloadStateError("only a verified staged Artifact can finalize")
    require_matching_receipt(row, request.object_receipt)
    binding = request.event_binding
    canonical = connection.execute(
        """
        SELECT payload #>> '{metadata,artifact_uri}' AS artifact_uri
        FROM session_events
        WHERE deployment_namespace = %s AND session_id = %s
          AND sequence = %s AND event_id = %s
        FOR SHARE
        """,
        (namespace, request.session_id, binding.sequence, binding.event_id),
    ).fetchone()
    if canonical is None or canonical["artifact_uri"] != binding.artifact_uri:
        raise CloudArtifactPayloadConflictError(
            "canonical Event does not bind the reserved Artifact URI"
        )
    revision = row["lifecycle_revision"] + 1
    updated = connection.execute(
        """
        UPDATE artifact_payload_metadata
        SET lifecycle_status = 'finalized', lifecycle_revision = %s,
            event_id = %s, event_sequence = %s, artifact_uri = %s,
            finalized_at = transaction_timestamp(), updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND artifact_id = %s
        RETURNING *
        """,
        (
            revision,
            binding.event_id,
            binding.sequence,
            binding.artifact_uri,
            namespace,
            request.artifact_id,
        ),
    ).fetchone()
    assert updated is not None
    insert_mutation(connection, namespace, request.artifact_id, "finalize", request, revision)
    return artifact_payload_from_row(updated)


def compensate(
    connection: Any,
    namespace: str,
    request: ArtifactCompensateRequest,
    authority: WorkerMutationAuthority,
) -> CloudArtifactPayloadRecord:
    assert_worker_boundary(connection, namespace, request.session_id, authority)
    return compensate_after_boundary(connection, namespace, request)


def compensate_after_boundary(
    connection: Any,
    namespace: str,
    request: ArtifactCompensateRequest,
) -> CloudArtifactPayloadRecord:
    row = lock_payload(connection, namespace, request.artifact_id, request.session_id)
    replay = mutation_replay(connection, namespace, row, "compensate", request)
    if replay is not None:
        return replay
    require_expected_revision(row, request.expected_lifecycle_revision)
    if row["lifecycle_status"] != "staged":
        raise CloudArtifactPayloadStateError("only a staged Artifact can be compensated")
    occupied = connection.execute(
        """
        SELECT event_id FROM session_events
        WHERE deployment_namespace = %s AND session_id = %s AND sequence = %s
        FOR SHARE
        """,
        (namespace, request.session_id, row["intended_event_sequence"]),
    ).fetchone()
    if occupied is not None:
        raise CloudArtifactPayloadConflictError(
            "reserved Event slot has a canonical outcome; compensation is unsafe"
        )
    _require_cleanup_evidence(row, request)
    revision = row["lifecycle_revision"] + 1
    updated = connection.execute(
        """
        UPDATE artifact_payload_metadata
        SET lifecycle_status = 'compensated', lifecycle_revision = %s,
            compensated_at = transaction_timestamp(), updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND artifact_id = %s
        RETURNING *
        """,
        (
            revision,
            namespace,
            request.artifact_id,
        ),
    ).fetchone()
    assert updated is not None
    insert_mutation(connection, namespace, request.artifact_id, "compensate", request, revision)
    return artifact_payload_from_row(updated)


def _require_cleanup_evidence(row: dict[str, Any], request: ArtifactCompensateRequest) -> None:
    cleanup = request.object_cleanup
    if row["object_version"] is None:
        verification = cleanup.verification
        if (
            verification is None
            or verification.status is not ArtifactObjectVerificationStatus.NOT_FOUND
            or verification.expectation.deployment_namespace != row["deployment_namespace"]
            or verification.expectation.sha256 != row["sha256"]
            or verification.expectation.size_bytes != row["size_bytes"]
        ):
            raise CloudArtifactPayloadConflictError("compensation lacks absence proof")
        return
    deletion = cleanup.deletion
    if deletion is None or deletion.request.object_version != row["object_version"]:
        raise CloudArtifactPayloadConflictError("compensation lacks exact-version deletion proof")
    expectation = deletion.request.expectation
    if (
        expectation.deployment_namespace != row["deployment_namespace"]
        or expectation.sha256 != row["sha256"]
        or expectation.size_bytes != row["size_bytes"]
    ):
        raise CloudArtifactPayloadConflictError("compensation deletion targets another object")
