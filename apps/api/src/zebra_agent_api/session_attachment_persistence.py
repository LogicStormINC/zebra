from __future__ import annotations

from agent_core.domain.attachments import SessionAttachmentRef, TextAttachmentInput
from agent_core.domain.events import SessionEvent
from agent_core.ports import ArtifactPayloadStorePort
from agent_storage import store_initial_text_attachments


def persist_initial_attachments(
    payload_store: ArtifactPayloadStorePort,
    events: tuple[SessionEvent, ...],
    attachments: tuple[TextAttachmentInput, ...],
) -> tuple[tuple[SessionEvent, ...], tuple[SessionAttachmentRef, ...]]:
    return store_initial_text_attachments(
        payload_store,
        events,
        attachments=attachments,
    )
