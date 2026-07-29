"""Worker-owned prune transitions for finalized cloud Artifact payloads."""

from typing import Any

from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadRecord,
    CloudArtifactPayloadStateError,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactBeginPruneRequest,
    ArtifactCompletePruneRequest,
)
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import (
    assert_worker_boundary,
    insert_mutation,
    lock_payload,
    mutation_replay,
    require_expected_revision,
)


def begin_prune(
    connection: Any,
    namespace: str,
    request: ArtifactBeginPruneRequest,
    authority: WorkerMutationAuthority,
) -> CloudArtifactPayloadRecord:
    assert_worker_boundary(connection, namespace, request.session_id, authority)
    row = lock_payload(connection, namespace, request.artifact_id, request.session_id)
    replay = mutation_replay(connection, namespace, row, "begin_prune", request)
    if replay is not None:
        return replay
    require_expected_revision(row, request.expected_lifecycle_revision)
    if row["lifecycle_status"] != "finalized":
        raise CloudArtifactPayloadStateError("only a finalized Artifact can begin pruning")
    revision = row["lifecycle_revision"] + 1
    updated = connection.execute(
        """
        UPDATE artifact_payload_metadata
        SET lifecycle_status = 'pruning', lifecycle_revision = %s,
            pruning_at = %s, updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND artifact_id = %s
        RETURNING *
        """,
        (revision, request.requested_at, namespace, request.artifact_id),
    ).fetchone()
    assert updated is not None
    insert_mutation(connection, namespace, request.artifact_id, "begin_prune", request, revision)
    return artifact_payload_from_row(updated)


def complete_prune(
    connection: Any,
    namespace: str,
    request: ArtifactCompletePruneRequest,
    authority: WorkerMutationAuthority,
) -> CloudArtifactPayloadRecord:
    assert_worker_boundary(connection, namespace, request.session_id, authority)
    row = lock_payload(connection, namespace, request.artifact_id, request.session_id)
    replay = mutation_replay(connection, namespace, row, "complete_prune", request)
    if replay is not None:
        return replay
    require_expected_revision(row, request.expected_lifecycle_revision)
    if row["lifecycle_status"] != "pruning" or row["object_version"] is None:
        raise CloudArtifactPayloadStateError("only a pruning Artifact can complete pruning")
    deletion = request.object_delete.request
    expectation = deletion.expectation
    if (
        expectation.deployment_namespace != namespace
        or expectation.artifact_id != request.artifact_id
        or expectation.sha256 != row["sha256"]
        or expectation.size_bytes != row["size_bytes"]
        or deletion.object_version != row["object_version"]
    ):
        raise CloudArtifactPayloadConflictError(
            "prune completion lacks exact-version deletion evidence"
        )
    revision = row["lifecycle_revision"] + 1
    updated = connection.execute(
        """
        UPDATE artifact_payload_metadata
        SET lifecycle_status = 'pruned', lifecycle_revision = %s,
            pruned_at = %s, updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND artifact_id = %s
        RETURNING *
        """,
        (revision, request.pruned_at, namespace, request.artifact_id),
    ).fetchone()
    assert updated is not None
    insert_mutation(
        connection,
        namespace,
        request.artifact_id,
        "complete_prune",
        request,
        revision,
    )
    return artifact_payload_from_row(updated)
