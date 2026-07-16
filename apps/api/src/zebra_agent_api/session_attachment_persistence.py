from __future__ import annotations

from pathlib import Path

from agent_core.domain.attachments import SessionAttachmentRef, TextAttachmentInput
from agent_core.domain.events import SessionEvent
from agent_storage import SQLiteArtifactPayloadStore, store_initial_text_attachments


def persist_initial_attachments(
    database_path: Path,
    events: tuple[SessionEvent, ...],
    attachments: tuple[TextAttachmentInput, ...],
) -> tuple[tuple[SessionEvent, ...], tuple[SessionAttachmentRef, ...]]:
    return store_initial_text_attachments(
        SQLiteArtifactPayloadStore(database_path),
        events,
        attachments=attachments,
    )
