"""Governed Artifact preflight; references never resolve through the network."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from agent_core.domain.artifact_payloads import ArtifactPayloadLifecycleStatus
from agent_core.domain.coverage_persistence import CoverageRunBinding, coverage_result_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.coverage import CoverageCommit

# ponytail: v1 reads one bounded immutable object; larger runs need sharded
# manifest/result Artifacts and streaming verification, never silent truncation.
MAX_COVERAGE_ARTIFACT_BYTES = 32 * 1024 * 1024


def read_artifact(
    artifacts: ArtifactPayloadStorePort, ref: str, digest: str, session_id: SessionId,
) -> bytes:
    if not ref.startswith("artifact://"):
        raise ValueError("coverage requires a governed artifact://UUID reference")
    artifact_id = ArtifactId(UUID(ref.removeprefix("artifact://")))
    if ref != f"artifact://{artifact_id}":
        raise ValueError("coverage Artifact reference must be canonical")
    metadata = artifacts.get_payload(artifact_id)
    now = datetime.now(UTC)
    if (
        metadata is None
        or metadata.artifact_id != artifact_id
        or metadata.session_id != session_id
        or metadata.lifecycle_status != ArtifactPayloadLifecycleStatus.ACTIVE
        or metadata.pruned_at is not None
        or (metadata.retained_until is not None and metadata.retained_until <= now)
        or metadata.sha256 != digest
        or not 0 <= metadata.size_bytes <= MAX_COVERAGE_ARTIFACT_BYTES
    ):
        raise ValueError("coverage Artifact is unavailable or bound to another Session")
    body = artifacts.read_payload_bytes(artifact_id)
    if (
        len(body) > MAX_COVERAGE_ARTIFACT_BYTES
        or len(body) != metadata.size_bytes or sha256(body).hexdigest() != digest
    ):
        raise ValueError("coverage Artifact bytes are corrupt")
    # Pruning may have raced the object read; immutable bytes alone do not prove lifecycle.
    if artifacts.get_payload(artifact_id) != metadata:
        raise ValueError("coverage Artifact metadata changed during preflight")
    return body


def read_manifest(
    artifacts: ArtifactPayloadStorePort, binding: CoverageRunBinding,
) -> tuple[CoverageRecord, ...]:
    return binding.verify_manifest(read_artifact(
        artifacts, binding.snapshot.manifest_artifact_ref,
        binding.manifest_artifact_digest, binding.session_id,
    ))


def verify_results(artifacts: ArtifactPayloadStorePort, request: CoverageCommit) -> None:
    body = read_artifact(
        artifacts, request.result_artifact_ref, request.result_artifact_digest, request.session_id,
    )
    if body != coverage_result_bytes(request.results):
        raise ValueError("coverage result Artifact disagrees with the exact canonical batch")
