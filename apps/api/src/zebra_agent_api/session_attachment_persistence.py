from __future__ import annotations

from pathlib import Path

from agent_core.application import attach_refs_to_user_event
from agent_core.domain.attachments import SessionAttachmentRef, TextAttachmentInput
from agent_core.domain.events import EventType, SessionEvent
from agent_storage import SQLiteArtifactPayloadStore, store_text_attachments


def persist_initial_attachments(
    database_path: Path,
    events: tuple[SessionEvent, ...],
    attachments: tuple[TextAttachmentInput, ...],
) -> tuple[tuple[SessionEvent, ...], tuple[SessionAttachmentRef, ...]]:
    if not attachments:
        return events, ()
    user_event = next(
        event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    refs = store_text_attachments(
        SQLiteArtifactPayloadStore(database_path),
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
