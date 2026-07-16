from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.attachments import (
    AttachmentContextInput,
    SessionAttachmentRef,
    TextAttachmentInput,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId

from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore


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
            attached_event if event.event_id == user_event.event_id else event
            for event in events
        ),
        refs,
    )
