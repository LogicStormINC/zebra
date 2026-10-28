"""Immutable Cloud input publication; the caller commits events/metadata atomically."""

from datetime import UTC, datetime
from hashlib import sha256

from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectPutRequest
from agent_core.domain.attachments import SessionAttachmentRef, TextAttachmentInput
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import ArtifactEventBinding, ArtifactReserveRequest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.image_attachments import ImageAttachmentInput
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort


def prepare_cloud_inputs(
    objects: ArtifactObjectStorePort,
    namespace: str,
    events: tuple[SessionEvent, ...],
    attachments: tuple[TextAttachmentInput | ImageAttachmentInput, ...],
) -> tuple[
    tuple[SessionEvent, ...],
    tuple[SessionAttachmentRef, ...],
    tuple[CloudArtifactPayloadRecord, ...],
]:
    if not attachments:
        return events, (), ()
    if len(attachments) > 16 or sum(len(item.payload) for item in attachments) > 64 * 1024 * 1024:
        raise ValueError("Cloud input publication exceeds its bounded batch")
    user = next(event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED)
    if len({item.attachment_id for item in attachments}) != len(attachments):
        raise ValueError("duplicate Cloud input identity")
    refs: list[SessionAttachmentRef] = []
    records: list[CloudArtifactPayloadRecord] = []
    materializations: list[SessionEvent] = []
    for item in attachments:
        expectation = ArtifactObjectExpectation(
            deployment_namespace=namespace,
            artifact_id=item.attachment_id,
            sha256=sha256(item.payload).hexdigest(),
            size_bytes=len(item.payload),
        )
        receipt = objects.put_if_absent(
            ArtifactObjectPutRequest(expectation=expectation, payload=item.payload)
        )
        if receipt.expectation != expectation:
            raise ValueError("Cloud input object receipt disagrees")
        uri = f"artifact://{item.attachment_id}"
        now = datetime.now(UTC)
        materialized = SessionEvent.create(
            session_id=user.session_id,
            sequence=events[-1].sequence + len(materializations) + 1,
            event_type=EventType.INPUT_ARTIFACT_STORED,
            actor=EventActor.SYSTEM,
            causation_id=user.event_id,
            created_at=now,
            payload=dict(
                artifact_id=str(item.attachment_id),
                uri=uri,
                file_name=item.file_name,
                sha256=expectation.sha256,
                size_bytes=expectation.size_bytes,
                message_event_id=str(user.event_id),
            ),
        )
        fields = item.model_dump(exclude={"payload", "width", "height"})
        refs.append(
            SessionAttachmentRef(
                **fields,
                message_event_id=user.event_id,
                sha256=expectation.sha256,
                size_bytes=expectation.size_bytes,
                image_width=item.width if isinstance(item, ImageAttachmentInput) else None,
                image_height=item.height if isinstance(item, ImageAttachmentInput) else None,
            )
        )
        records.append(
            CloudArtifactPayloadRecord(
                deployment_namespace=namespace,
                reservation=ArtifactReserveRequest(
                    artifact_id=item.attachment_id,
                    session_id=user.session_id,
                    intended_event_sequence=materialized.sequence,
                    kind=item.source_type,
                    mime_type=item.media_type,
                    sha256=expectation.sha256,
                    size_bytes=expectation.size_bytes,
                    idempotency_key=f"input:{materialized.event_id}",
                    file_name=item.file_name,
                    created_at=now,
                ),
                lifecycle_status=CloudArtifactPayloadLifecycleStatus.FINALIZED,
                lifecycle_revision=2,
                object_receipt=receipt,
                event_binding=ArtifactEventBinding(
                    session_id=user.session_id,
                    event_id=materialized.event_id,
                    sequence=materialized.sequence,
                    artifact_uri=uri,
                ),
                finalized_at=now,
            )
        )
        materializations.append(materialized)
    attached = attach_refs_to_user_event(user, tuple(refs))
    return (
        (
            *tuple(attached if event.event_id == user.event_id else event for event in events),
            *materializations,
        ),
        tuple(refs),
        tuple(records),
    )
