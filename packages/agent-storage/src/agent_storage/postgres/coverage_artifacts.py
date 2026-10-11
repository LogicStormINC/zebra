"""Governed Artifact preflight; references never resolve through the network."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadLifecycleStatus,
    StoredArtifactPayload,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding, coverage_result_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import (
    ArtifactPayloadStorePort,
    BoundedArtifactPayloadReaderPort,
    VerifiedArtifactPayloadReaderPort,
)
from agent_core.ports.coverage import CoverageCommit

from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore
from agent_storage.postgres.artifact_payload_transaction_support import lock_payload

# ponytail: v1 reads one bounded immutable object; larger runs need sharded
# manifest/result Artifacts and streaming verification, never silent truncation.
MAX_COVERAGE_ARTIFACT_BYTES = 32 * 1024 * 1024


def _identity(ref: str) -> ArtifactId:
    if not ref.startswith("artifact://"):
        raise ValueError("coverage requires a governed artifact://UUID reference")
    artifact_id = ArtifactId(UUID(ref.removeprefix("artifact://")))
    if ref != f"artifact://{artifact_id}":
        raise ValueError("coverage Artifact reference must be canonical")
    return artifact_id


def _validate_metadata(
    metadata: StoredArtifactPayload | None,
    artifact_id: ArtifactId,
    session_id: SessionId,
    digest: str,
) -> StoredArtifactPayload:
    if (
        metadata is None
        or metadata.artifact_id != artifact_id
        or metadata.session_id != session_id
        or metadata.lifecycle_status != ArtifactPayloadLifecycleStatus.ACTIVE
        or metadata.pruned_at is not None
        or (metadata.retained_until is not None and metadata.retained_until <= datetime.now(UTC))
        or metadata.sha256 != digest
        or not 0 <= metadata.size_bytes <= MAX_COVERAGE_ARTIFACT_BYTES
    ):
        raise ValueError("coverage Artifact is unavailable or bound to another Session")
    return metadata


def check_artifact_lifecycle(
    artifacts: ArtifactPayloadStorePort,
    ref: str,
    digest: str,
    session_id: SessionId,
    *,
    connection: Any = None,
    deployment: str = "",
) -> StoredArtifactPayload:
    artifact_id = _identity(ref)
    row = None
    if connection is not None and not isinstance(artifacts, SQLiteArtifactPayloadStore):
        # Cloud evidence must live in this transaction's database. Never silently
        # fall back to an unlocked reader when its governed row is absent.
        row = pinned_payload_row(artifacts, connection, deployment, artifact_id, session_id)
        if row["lifecycle_status"] != "finalized":
            raise ValueError("coverage Artifact is unavailable")
    metadata = _validate_metadata(
        artifacts.get_payload(artifact_id), artifact_id, session_id, digest
    )
    if row is not None and (
        row["sha256"] != metadata.sha256
        or row["size_bytes"] != metadata.size_bytes
        or row["retained_until"] != metadata.retained_until
    ):
        raise ValueError("coverage Artifact metadata disagrees with locked lifecycle")
    return metadata


def pinned_payload_row(
    artifacts: Any, connection: Any, deployment: str,
    artifact_id: ArtifactId, session_id: SessionId,
) -> dict[str, Any]:
    """Share same-transaction FOR UPDATE rows only through the private proof reader.

    The native reader validates connection, deployment and Session identity and
    permits reuse only for the configured pure verifier. Ordinary readers lock
    afresh; arbitrary derivation callbacks retain the original native checks.
    """
    pinned = getattr(artifacts, "_native_payload_row", None)
    return (pinned(connection, deployment, artifact_id, session_id) if callable(pinned)
            else lock_payload(connection, deployment, artifact_id, session_id))


def read_artifact(
    artifacts: ArtifactPayloadStorePort,
    ref: str,
    digest: str,
    session_id: SessionId,
) -> bytes:
    return read_verified_artifact(artifacts, ref, digest, session_id)[1]


def read_verified_artifact(
    artifacts: ArtifactPayloadStorePort,
    ref: str,
    digest: str,
    session_id: SessionId,
) -> tuple[StoredArtifactPayload, bytes]:
    """Return fresh verified metadata with bytes, avoiding a second metadata lookup."""
    artifact_id = _identity(ref)
    verified = isinstance(artifacts, VerifiedArtifactPayloadReaderPort)
    if isinstance(artifacts, VerifiedArtifactPayloadReaderPort):
        metadata, body = artifacts.read_payload_verified_bounded(
            artifact_id, session_id=session_id, digest=digest, max_bytes=MAX_COVERAGE_ARTIFACT_BYTES
        )
        _validate_metadata(metadata, artifact_id, session_id, digest)
    else:
        metadata = check_artifact_lifecycle(artifacts, ref, digest, session_id)
        if not isinstance(artifacts, BoundedArtifactPayloadReaderPort):
            raise ValueError("coverage requires physically bounded Artifact reads")
        body = artifacts.read_payload_bytes_bounded(
            artifact_id, max_bytes=MAX_COVERAGE_ARTIFACT_BYTES
        )
    if (
        len(body) > MAX_COVERAGE_ARTIFACT_BYTES
        or len(body) != metadata.size_bytes
        or sha256(body).hexdigest() != digest
    ):
        raise ValueError("coverage Artifact bytes are corrupt")
    # Pruning may have raced the object read; immutable bytes alone do not prove lifecycle.
    if not verified and artifacts.get_payload(artifact_id) != metadata:
        raise ValueError("coverage Artifact metadata changed during preflight")
    return metadata, body


def read_manifest(
    artifacts: ArtifactPayloadStorePort,
    binding: CoverageRunBinding,
) -> tuple[CoverageRecord, ...]:
    return binding.verify_manifest(
        read_artifact(
            artifacts,
            binding.snapshot.manifest_artifact_ref,
            binding.manifest_artifact_digest,
            binding.session_id,
        )
    )


def verify_results(artifacts: ArtifactPayloadStorePort, request: CoverageCommit) -> None:
    body = read_artifact(
        artifacts,
        request.result_artifact_ref,
        request.result_artifact_digest,
        request.session_id,
    )
    if body != coverage_result_bytes(request.results):
        raise ValueError("coverage result Artifact disagrees with the exact canonical batch")
