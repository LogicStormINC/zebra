from __future__ import annotations

from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.events import EventType, SessionEvent


def attach_refs_to_user_event(
    event: SessionEvent,
    attachments: tuple[SessionAttachmentRef, ...],
) -> SessionEvent:
    if not attachments:
        return event
    if event.event_type is not EventType.USER_MESSAGE_RECEIVED:
        raise ValueError("attachments require an ordinary user message event")
    if any(attachment.message_event_id != event.event_id for attachment in attachments):
        raise ValueError("attachment message_event_id must match the user event")
    return event.model_copy(
        update={
            "payload": {
                **event.payload,
                "attachments": [attachment.to_mapping() for attachment in attachments],
            }
        }
    )


def attachment_refs_from_event(event: SessionEvent) -> tuple[SessionAttachmentRef, ...]:
    if event.event_type is not EventType.USER_MESSAGE_RECEIVED:
        return ()
    raw = event.payload.get("attachments")
    if not isinstance(raw, list):
        return ()
    refs: list[SessionAttachmentRef] = []
    for item in raw:
        try:
            ref = SessionAttachmentRef.model_validate(item)
        except ValueError:
            continue
        if ref.message_event_id == event.event_id:
            refs.append(ref)
    return tuple(refs)
