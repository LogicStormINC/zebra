from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.domain.artifact_payloads import ArtifactPayloadStatus, ArtifactPayloadWrite
from agent_core.domain.attachments import (
    AttachmentContextInput,
    SessionAttachmentRef,
    TextAttachmentInput,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.model_media import ModelMediaInput
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort

from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore


@dataclass(frozen=True)
class RegisteredTaskMedia:
    attachment: SessionAttachmentRef
    source_session_id: SessionId


class TaskAttachmentMediaResolver:
    def __init__(
        self,
        store: ArtifactPayloadStorePort,
        registered_media: tuple[RegisteredTaskMedia, ...],
    ) -> None:
        self._store = store
        expected: dict[ArtifactId, tuple[ModelMediaInput, SessionId]] = {}
        for ordinal, registered in enumerate(registered_media):
            attachment = registered.attachment
            if not attachment.media_type.startswith("image/"):
                continue
            media = ModelMediaInput(
                artifact_id=attachment.attachment_id,
                media_type=attachment.media_type,
                sha256=attachment.sha256,
                size_bytes=attachment.size_bytes,
                display_name=attachment.file_name,
                ordinal=ordinal,
                source_message_id=attachment.message_event_id,
            )
            if media.artifact_id in expected:
                raise ValueError("task media artifact reference is duplicated")
            expected[media.artifact_id] = (media, registered.source_session_id)
        self._expected = expected

    @property
    def media_inputs(self) -> tuple[ModelMediaInput, ...]:
        return tuple(media for media, _session_id in self._expected.values())

    def resolve_media(self, media_input: ModelMediaInput) -> bytes:
        try:
            expected, source_session_id = self._expected[media_input.artifact_id]
        except KeyError as exc:
            raise ValueError("model media artifact is not registered for this task") from exc
        if media_input != expected:
            raise ValueError("model media reference does not match task registration")
        inspection = self._store.inspect_payload(media_input.artifact_id)
        if inspection is None or inspection.status is not ArtifactPayloadStatus.AVAILABLE:
            raise ValueError("model media payload is unavailable")
        payload = inspection.payload
        if payload.session_id != source_session_id:
            raise ValueError("model media artifact is not authorized for its source session")
        if (
            payload.mime_type != expected.media_type
            or payload.size_bytes != expected.size_bytes
            or payload.sha256 != expected.sha256
        ):
            raise ValueError("model media payload metadata does not match task registration")
        content = self._store.read_payload_bytes(media_input.artifact_id)
        if len(content) != expected.size_bytes or sha256(content).hexdigest() != expected.sha256:
            raise ValueError("model media payload content does not match task registration")
        return content


def store_text_attachments(
    store: SQLiteArtifactPayloadStore,
    *,
    session_id: SessionId,
    message_event: SessionEvent,
    attachments: tuple[TextAttachmentInput, ...],
    created_at: datetime,
) -> tuple[SessionAttachmentRef, ...]:
    stored_ids = []
    refs: list[SessionAttachmentRef] = []
    try:
        for attachment in attachments:
            stored = store.store_payload(
                ArtifactPayloadWrite(
                    session_id=session_id,
                    kind=attachment.source_type,
                    mime_type=attachment.media_type,
                    payload=attachment.payload,
                    file_name=attachment.file_name,
                    created_at=created_at,
                ),
                artifact_id=attachment.attachment_id,
            )
            stored_ids.append(stored.artifact_id)
            refs.append(
                SessionAttachmentRef(
                    attachment_id=stored.artifact_id,
                    message_event_id=message_event.event_id,
                    file_name=attachment.file_name,
                    media_type=stored.mime_type,
                    size_bytes=stored.size_bytes,
                    sha256=stored.sha256,
                    source_type=attachment.source_type,
                    source_server=attachment.source_server,
                    source_id=attachment.source_id,
                    source_argument_names=attachment.source_argument_names,
                    original_media_type=attachment.original_media_type,
                    original_size_bytes=attachment.original_size_bytes,
                    original_sha256=attachment.original_sha256,
                    page_count=attachment.page_count,
                    paragraph_count=attachment.paragraph_count,
                    worksheet_count=attachment.worksheet_count,
                    cell_count=attachment.cell_count,
                    slide_count=attachment.slide_count,
                    extraction_status=attachment.extraction_status,
                )
            )
    except Exception:
        for artifact_id in stored_ids:
            store.prune_payload(artifact_id, pruned_at=created_at)
        raise
    return tuple(refs)


def load_attachment_contexts(
    store: SQLiteArtifactPayloadStore,
    refs: tuple[SessionAttachmentRef, ...],
) -> tuple[AttachmentContextInput, ...]:
    contexts: list[AttachmentContextInput] = []
    for ref in refs:
        if ref.storage_kind == "task_workspace":
            continue
        payload = store.read_payload_bytes(ref.attachment_id)
        if len(payload) != ref.size_bytes:
            raise ValueError("attachment payload size does not match durable metadata")
        if sha256(payload).hexdigest() != ref.sha256:
            raise ValueError("attachment payload digest does not match durable metadata")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("attachment payload is no longer valid UTF-8") from exc
        contexts.append(
            AttachmentContextInput(
                attachment_id=ref.attachment_id,
                file_name=ref.file_name,
                media_type=ref.media_type,
                text=text,
                source_type=ref.source_type,
                source_server=ref.source_server,
                source_id=ref.source_id,
                source_argument_names=ref.source_argument_names,
                original_media_type=ref.original_media_type,
                original_size_bytes=ref.original_size_bytes,
                original_sha256=ref.original_sha256,
                page_count=ref.page_count,
                paragraph_count=ref.paragraph_count,
                worksheet_count=ref.worksheet_count,
                cell_count=ref.cell_count,
                slide_count=ref.slide_count,
                extraction_status=ref.extraction_status,
            )
        )
    return tuple(contexts)


def store_initial_text_attachments(
    store: SQLiteArtifactPayloadStore,
    events: tuple[SessionEvent, ...],
    attachments: tuple[TextAttachmentInput, ...],
) -> tuple[tuple[SessionEvent, ...], tuple[SessionAttachmentRef, ...]]:
    if not attachments:
        return events, ()
    user_event = next(
        event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    refs = store_text_attachments(
        store,
        session_id=user_event.session_id,
        message_event=user_event,
        attachments=attachments,
        created_at=user_event.created_at,
    )
    attached_event = attach_refs_to_user_event(user_event, refs)
    return (
        tuple(
            attached_event if event.event_id == user_event.event_id else event for event in events
        ),
        refs,
    )
