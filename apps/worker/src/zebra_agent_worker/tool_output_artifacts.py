"""Cloud Artifact commit orchestration at the terminal Tool Event boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock

from agent_core.domain.artifact_objects import (
    ArtifactObjectCleanupEvidence,
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadLifecycleStatus,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactCompensateRequest,
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    ArtifactMetadataQuery,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId, new_artifact_id
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_core.ports.cloud_artifact_payload_store import CloudArtifactPayloadStorePort
from agent_tools import ToolOutputProjector

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder

_TERMINAL_TOOL_EVENTS = {
    EventType.TOOL_EXECUTION_COMPLETED,
    EventType.TOOL_EXECUTION_FAILED,
}


@dataclass(frozen=True, slots=True)
class _PendingToolOutput:
    artifact_id: ArtifactId
    payload: bytes
    file_name: str
    created_at: datetime

    @property
    def uri(self) -> str:
        return f"artifact://{self.artifact_id}"


@dataclass(frozen=True, slots=True)
class PreparedCloudArtifact:
    artifact_id: ArtifactId
    session_id: SessionId
    receipt: ArtifactObjectReceipt
    idempotency_scope: str
    intended_event_sequence: int

    @property
    def uri(self) -> str:
        return f"artifact://{self.artifact_id}"

    def finalize_request(self, event: SessionEvent) -> ArtifactFinalizeRequest:
        return ArtifactFinalizeRequest(
            artifact_id=self.artifact_id,
            session_id=self.session_id,
            expected_lifecycle_revision=1,
            idempotency_key=f"{self.idempotency_scope}-finalize:{self.artifact_id}",
            event_binding=ArtifactEventBinding(
                session_id=self.session_id,
                event_id=event.event_id,
                sequence=event.sequence,
                artifact_uri=self.uri,
            ),
            object_receipt=self.receipt,
            finalized_at=event.created_at,
        )


class CloudToolOutputArtifactCoordinator:
    """Bind captured bytes to the exact terminal Event chosen by the recorder."""

    def __init__(
        self,
        session_id: SessionId,
        metadata_store: CloudArtifactPayloadStorePort,
        object_store: ArtifactObjectStorePort,
    ) -> None:
        self._session_id = session_id
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._pending: dict[str, _PendingToolOutput] = {}
        self._lock = Lock()
        self.output_projector = ToolOutputProjector(self._capture_text)

    def append_draft(
        self,
        draft: HarnessEventDraft,
        recorder: DurableHarnessEventRecorder,
    ) -> SessionEvent:
        pending = self._pending_for_draft(draft)
        if pending is None:
            return recorder.append_draft(draft)
        authority = recorder.worker_mutation_authority
        if authority is None:
            raise ValueError("cloud Artifact output requires Worker mutation authority")
        prepared = self.stage_bytes(
            artifact_id=pending.artifact_id,
            payload=pending.payload,
            kind="tool_output",
            mime_type="text/plain",
            file_name=pending.file_name,
            created_at=pending.created_at,
            intended_event_sequence=recorder.next_sequence,
            authority=authority,
            idempotency_scope="tool-output",
        )
        try:
            event = recorder.prepare(draft.event_type, draft.actor, draft.payload)
            if event.sequence != prepared.intended_event_sequence:
                raise ValueError("reserved Artifact Event sequence changed before append")
        except Exception:
            # ponytail: once object I/O succeeds, inline deletion is unsafe without
            # a fenced DB compensation claim; leave staged for management reconcile.
            raise
        persisted = recorder.append_event(event)
        finalized_authority = recorder.worker_mutation_authority
        if finalized_authority is None:
            raise ValueError("cloud Artifact Event commit lost Worker authority")
        self._metadata_store.finalize_for_worker(
            prepared.finalize_request(persisted),
            authority=finalized_authority,
        )
        self.release_pending(pending.uri)
        return persisted

    def stage_bytes(
        self,
        *,
        artifact_id: ArtifactId,
        payload: bytes,
        kind: str,
        mime_type: str,
        file_name: str,
        created_at: datetime,
        intended_event_sequence: int,
        authority: WorkerMutationAuthority,
        idempotency_scope: str,
        allow_finalized_sequence_replay: bool = False,
    ) -> PreparedCloudArtifact:
        reservation = ArtifactReserveRequest(
            artifact_id=artifact_id,
            session_id=self._session_id,
            intended_event_sequence=intended_event_sequence,
            kind=kind,
            mime_type=mime_type,
            sha256=sha256(payload).hexdigest(),
            size_bytes=len(payload),
            idempotency_key=f"{idempotency_scope}-reserve:{artifact_id}",
            file_name=file_name,
            created_at=created_at,
        )
        expectation = ArtifactObjectExpectation(
            deployment_namespace=authority.deployment_namespace,
            artifact_id=artifact_id,
            sha256=reservation.sha256,
            size_bytes=reservation.size_bytes,
        )
        existing = self._metadata_store.get_metadata(
            ArtifactMetadataQuery(
                deployment_namespace=authority.deployment_namespace,
                artifact_id=artifact_id,
                session_id=self._session_id,
            )
        )
        if existing is not None and existing.object_receipt is not None:
            same_reservation = existing.reservation == reservation
            if (
                allow_finalized_sequence_replay
                and existing.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED
            ):
                same_reservation = (
                    existing.reservation.model_copy(
                        update={"intended_event_sequence": intended_event_sequence}
                    )
                    == reservation
                )
            if not same_reservation or existing.object_receipt.expectation != expectation:
                raise CloudArtifactPayloadConflictError(
                    "stable Artifact identity was reused with different payload meaning"
                )
            return PreparedCloudArtifact(
                artifact_id,
                self._session_id,
                existing.object_receipt,
                idempotency_scope,
                intended_event_sequence,
            )
        self._metadata_store.reserve_for_worker(reservation, authority=authority)
        receipt = self._put_or_recover(
            ArtifactObjectPutRequest(expectation=expectation, payload=payload),
            reservation,
            authority,
            idempotency_scope=idempotency_scope,
        )
        self._metadata_store.record_object_for_worker(
            ArtifactRecordObjectRequest(
                artifact_id=artifact_id,
                session_id=self._session_id,
                expected_lifecycle_revision=0,
                idempotency_key=f"{idempotency_scope}-record:{artifact_id}",
                object_receipt=receipt,
            ),
            authority=authority,
        )
        return PreparedCloudArtifact(
            artifact_id,
            self._session_id,
            receipt,
            idempotency_scope,
            intended_event_sequence,
        )

    def stage_pending_output(
        self,
        artifact_uri: str,
        *,
        intended_event_sequence: int,
        authority: WorkerMutationAuthority,
    ) -> PreparedCloudArtifact | None:
        with self._lock:
            pending = self._pending.get(artifact_uri)
        if pending is None:
            return None
        return self.stage_bytes(
            artifact_id=pending.artifact_id,
            payload=pending.payload,
            kind="tool_output",
            mime_type="text/plain",
            file_name=pending.file_name,
            created_at=pending.created_at,
            intended_event_sequence=intended_event_sequence,
            authority=authority,
            idempotency_scope="tool-output",
        )

    def read_verified(self, artifact_id: ArtifactId, *, namespace: str) -> bytes:
        metadata = self._metadata_store.get_metadata(
            ArtifactMetadataQuery(
                deployment_namespace=namespace,
                artifact_id=artifact_id,
                session_id=self._session_id,
            )
        )
        if (
            metadata is None
            or metadata.lifecycle_status is not CloudArtifactPayloadLifecycleStatus.FINALIZED
            or metadata.object_receipt is None
        ):
            raise FileNotFoundError("cloud Artifact payload is unavailable")
        return self._object_store.read_verified(metadata.object_receipt.expectation)

    def release_pending(self, artifact_uri: str) -> None:
        with self._lock:
            self._pending.pop(artifact_uri, None)

    def _put_or_recover(
        self,
        request: ArtifactObjectPutRequest,
        reservation: ArtifactReserveRequest,
        authority: WorkerMutationAuthority,
        *,
        idempotency_scope: str,
    ) -> ArtifactObjectReceipt:
        try:
            return self._object_store.put_if_absent(request)
        except Exception as put_error:
            try:
                verification = self._object_store.verify(request.expectation)
            except Exception as verification_error:
                raise ExceptionGroup(
                    "cloud Artifact put and verification both failed",
                    [put_error, verification_error],
                ) from put_error
            if verification.status is ArtifactObjectVerificationStatus.VERIFIED:
                assert verification.receipt is not None
                return verification.receipt
            if verification.status is ArtifactObjectVerificationStatus.NOT_FOUND:
                try:
                    self._metadata_store.compensate_for_worker(
                        ArtifactCompensateRequest(
                            artifact_id=reservation.artifact_id,
                            session_id=self._session_id,
                            expected_lifecycle_revision=0,
                            idempotency_key=(
                                f"{idempotency_scope}-compensate:{reservation.artifact_id}"
                            ),
                            object_cleanup=ArtifactObjectCleanupEvidence(verification=verification),
                            compensated_at=datetime.now(UTC),
                        ),
                        authority=authority,
                    )
                except Exception as compensation_error:
                    raise ExceptionGroup(
                        "cloud Artifact put and compensation both failed",
                        [put_error, compensation_error],
                    ) from put_error
            raise put_error from None

    def _capture_text(self, content: str, file_name: str) -> str:
        pending = _PendingToolOutput(
            artifact_id=new_artifact_id(),
            payload=content.encode("utf-8"),
            file_name=file_name,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._pending[pending.uri] = pending
        return pending.uri

    def _pending_for_draft(self, draft: HarnessEventDraft) -> _PendingToolOutput | None:
        if draft.event_type not in _TERMINAL_TOOL_EVENTS:
            return None
        metadata = draft.payload.get("metadata")
        uri = metadata.get("artifact_uri") if isinstance(metadata, dict) else None
        if not isinstance(uri, str):
            return None
        with self._lock:
            pending = self._pending.get(uri)
        if pending is None and uri.startswith("artifact://"):
            raise ValueError("managed Artifact URI has no captured payload")
        return pending
