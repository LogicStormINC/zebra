from __future__ import annotations

from pathlib import Path

from agent_core.application import attach_refs_to_user_event
from agent_core.domain.attachments import SessionAttachmentRef, TextAttachmentInput
from agent_core.domain.events import EventType, SessionEvent
from agent_storage import SQLiteArtifactPayloadStore, store_initial_text_attachments

from zebra_agent_api.task_image_attachments import StagedTaskImages


def persist_initial_attachments(
    database_path: Path,
    events: tuple[SessionEvent, ...],
    attachments: tuple[TextAttachmentInput, ...],
    staged_images: StagedTaskImages | None = None,
) -> tuple[tuple[SessionEvent, ...], tuple[SessionAttachmentRef, ...]]:
    store = SQLiteArtifactPayloadStore(database_path)
    persisted_events, refs = store_initial_text_attachments(
        store,
        events,
        attachments=attachments,
    )
    if staged_images is None or not staged_images.images:
        return persisted_events, refs
    user_event = next(
        event for event in persisted_events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    staged_images.persist_payloads(
        store,
        session_id=user_event.session_id,
        created_at=user_event.created_at,
    )
    image_refs = staged_images.refs_for(user_event.event_id)
    attached_event = attach_refs_to_user_event(user_event, image_refs)
    return (
        tuple(
            attached_event if event.event_id == user_event.event_id else event
            for event in persisted_events
        ),
        (*refs, *image_refs),
    )
