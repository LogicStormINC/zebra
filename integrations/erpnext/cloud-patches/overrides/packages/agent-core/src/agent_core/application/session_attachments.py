from __future__ import annotations

from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.events import EventType, SessionEvent


def attach_refs_to_user_event(
    event: SessionEvent,
    attachments: tuple[SessionAttachmentRef, ...],
) -> SessionEvent:
    if not attachments:
        return event
    if event.event_type not in {EventType.USER_MESSAGE_RECEIVED, EventType.CLARIFICATION_RESPONDED}:
        raise ValueError("attachments require a user input event")
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
    if event.event_type not in {EventType.USER_MESSAGE_RECEIVED, EventType.CLARIFICATION_RESPONDED}:
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


def validate_attachment_context_budget(attachments) -> None:
    """Clarification extends one input context, so retain native admission caps."""
    from agent_core.domain.attachments import SessionAttachmentRef

    sizes = [
        (
            item.media_type,
            item.size_bytes if isinstance(item, SessionAttachmentRef) else len(item.payload),
            getattr(item, "original_size_bytes", None) or 0,
        )
        for item in attachments
    ]
    if (
        len(sizes) > 4
        or sum(size for media, size, _ in sizes if media.startswith("image/")) > 32 * 1024 * 1024
        or sum(size for media, size, _ in sizes if not media.startswith("image/")) > 131072
        or sum(original for _, _, original in sizes) > 8 * 1024 * 1024
    ):
        raise ValueError("attachment context exceeds native four-file/aggregate limits")
