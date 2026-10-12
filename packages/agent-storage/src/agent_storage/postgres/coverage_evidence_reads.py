"""Operation-owned verified bytes; unknown identities never fall back to object I/O."""

from contextlib import nullcontext
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadLifecycleStatus,
    StoredArtifactPayload,
)
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.identifiers import ArtifactId, SessionId

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES
from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention
from agent_storage.postgres.coverage_proof_prefetch import locked_page
from agent_storage.worker_capability_configuration import NATIVE_CONTINUATION_VERIFIER


class EvidenceOperationReads:
    def __init__(
        self, source: Any, connection: Any, deployment: str, binding: CoverageRunBinding,
        verified: tuple[tuple[CloudArtifactPayloadRecord, bytes], ...],
        *, derive: Any = None,
    ) -> None:
        self.source, self.connection, self.deployment, self.binding = (
            source, connection, deployment, binding,
        )
        self._derive = derive
        if (not 1 <= len(verified) <= 1000
                or len({record.artifact_id for record, _ in verified}) != len(verified)
                or sum(len(body) for _, body in verified) > MAX_COVERAGE_ARTIFACT_BYTES):
            raise ValueError("evidence operation exceeds bounded proof scope")
        self.verified = {record.artifact_id: (record, body) for record, body in verified}
        self.rows, self.events = locked_page(connection, deployment, binding, tuple(self.verified))
        for identifier, (record, body) in self.verified.items():
            if (artifact_payload_from_row(self.rows[identifier]) != record
                    or record.deployment_namespace != deployment
                    or record.session_id != binding.session_id
                    or record.lifecycle_status != "finalized" or record.object_receipt is None
                    or record.reservation.size_bytes != len(body)
                    or record.reservation.sha256 != sha256(body).hexdigest()):
                raise ValueError("verified evidence disagrees with fresh locked full record")
        # The full page is freshly loaded above; only CPU retention validation
        # remains here. The operation owner revalidates originals after callbacks.
        for identifier in self.verified:
            self.get_payload(identifier)

    def _boundary(self, connection: Any, deployment: str, session: SessionId) -> None:
        if (self.connection is None or connection is not self.connection
                or deployment != self.deployment or session != self.binding.session_id):
            raise ValueError("evidence operation proof owner conflicts or has ended")

    def _native_payload_row(
        self, connection: Any, deployment: str, artifact_id: ArtifactId, session_id: SessionId,
    ) -> Any:
        self._boundary(connection, deployment, session_id)
        if artifact_id not in self.rows:
            raise ValueError("evidence requires outside-transaction prefetch")
        return self.rows[artifact_id]

    def _native_materialized_sources(
        self, connection: Any, deployment: str, session_id: SessionId, ref: str, *,
        event_id: Any = None,
    ) -> list[Any]:
        self._boundary(connection, deployment, session_id)
        return [event for event in self.events if event["event_id"] == event_id or (
            event["event_type"] == "coverage_artifact_materialized"
            and event["payload"].get("metadata", {}).get("artifact_uri") == ref
        )]

    def _prefetch_proof(self, identifiers: tuple[ArtifactId, ...]) -> None:
        self._boundary(self.connection, self.deployment, self.binding.session_id)
        if any(identifier not in self.verified for identifier in identifiers):
            raise ValueError("evidence requires outside-transaction prefetch")

    def _locked_proof_scope(
        self, connection: Any, deployment: str, binding: CoverageRunBinding, **kwargs: Any,
    ) -> Any:
        self._boundary(connection, deployment, binding.session_id)
        if binding != self.binding or kwargs.get("final_certification"):
            raise ValueError("evidence operation cannot replace final certification")
        return nullcontext(self)

    def _execution_receipt_verifier(self, derive: Any) -> str | None:
        self._boundary(self.connection, self.deployment, self.binding.session_id)
        return (NATIVE_CONTINUATION_VERIFIER
                if derive is self._derive and derive is not None else None)

    def get_payload(self, artifact_id: ArtifactId) -> StoredArtifactPayload:
        self._prefetch_proof((artifact_id,))
        record, _ = self.verified[artifact_id]
        request = record.reservation
        if request.retained_until is not None and request.retained_until <= datetime.now(UTC):
            raise ValueError("evidence operation Artifact retention expired")
        return StoredArtifactPayload(
            artifact_id=artifact_id, session_id=record.session_id, kind=request.kind,
            mime_type=request.mime_type, uri=record.uri, sha256=request.sha256,
            size_bytes=request.size_bytes,
            created_at=request.created_at, retained_until=request.retained_until,
            lifecycle_status=ArtifactPayloadLifecycleStatus.ACTIVE,
        )

    def read_payload_verified_bounded(
        self, artifact_id: ArtifactId, *, session_id: SessionId, digest: str, max_bytes: int,
    ) -> tuple[StoredArtifactPayload, bytes]:
        metadata = self.get_payload(artifact_id)
        if (session_id != self.binding.session_id or metadata.sha256 != digest
                or type(max_bytes) is not int or not 0 <= max_bytes <= MAX_COVERAGE_ARTIFACT_BYTES
                or metadata.size_bytes > max_bytes):
            raise ValueError("evidence operation read identity/digest/bound conflicts")
        return metadata, self.verified[artifact_id][1]

    def read_payload_bytes_bounded(self, artifact_id: ArtifactId, *, max_bytes: int) -> bytes:
        metadata = self.get_payload(artifact_id)
        return self.read_payload_verified_bounded(
            artifact_id, session_id=self.binding.session_id, digest=metadata.sha256,
            max_bytes=max_bytes,
        )[1]

    def revalidate(self) -> None:
        self._boundary(self.connection, self.deployment, self.binding.session_id)
        rows, events = locked_page(
            self.connection, self.deployment, self.binding, tuple(self.verified),
        )
        if rows != self.rows or events != self.events:
            raise ValueError("evidence full lifecycle or canonical Event changed during callback")
        for identifier in self.verified:
            self.get_payload(identifier)

    def close(self) -> None:
        self.connection = None
        self.verified.clear()
        self.rows.clear()
        self.events.clear()

    def finish_retention(self, deadline: datetime) -> None:
        self._boundary(self.connection, self.deployment, self.binding.session_id)
        earliest = min((deadline, self.binding.snapshot.expires_at, *(
            record.reservation.retained_until for record, _ in self.verified.values()
            if record.reservation.retained_until is not None
        )))
        check_checkpoint_retention(self.connection, [earliest])
