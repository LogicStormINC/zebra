from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.identifiers import SessionId, new_artifact_id, new_event_id, new_session_id
from agent_storage import SQLiteArtifactPayloadStore
from agent_storage.session_attachments import RegisteredTaskMedia, TaskAttachmentMediaResolver

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
IMAGE = b"\x89PNG\r\n\x1a\nZEBRA-NATIVE-MEDIA"


def test_task_media_resolver_reads_only_the_registered_authorized_image(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.sqlite")
    source_session_id = new_session_id()
    reference = _reference()
    store.store_payload(
        _payload(source_session_id),
        artifact_id=reference.attachment_id,
    )
    resolver = TaskAttachmentMediaResolver(
        store,
        (RegisteredTaskMedia(reference, source_session_id),),
    )

    [media] = resolver.media_inputs

    assert resolver.resolve_media(media) == IMAGE
    with pytest.raises(ValueError, match="not registered"):
        resolver.resolve_media(replace(media, artifact_id=new_artifact_id()))


def test_task_media_resolver_rejects_cross_session_payload_even_with_matching_metadata(
    tmp_path: Path,
) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.sqlite")
    reference = _reference()
    store.store_payload(
        _payload(new_session_id()),
        artifact_id=reference.attachment_id,
    )
    resolver = TaskAttachmentMediaResolver(
        store,
        (RegisteredTaskMedia(reference, new_session_id()),),
    )

    with pytest.raises(ValueError, match="not authorized"):
        resolver.resolve_media(resolver.media_inputs[0])


def test_task_media_resolver_rejects_pruned_or_tampered_payload_content(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.sqlite")
    source_session_id = new_session_id()
    reference = _reference()
    stored = store.store_payload(
        _payload(source_session_id),
        artifact_id=reference.attachment_id,
    )
    resolver = TaskAttachmentMediaResolver(
        store,
        (RegisteredTaskMedia(reference, source_session_id),),
    )

    Path((stored.access_uri or "").removeprefix("file://")).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="content does not match"):
        resolver.resolve_media(resolver.media_inputs[0])

    store.prune_payload(reference.attachment_id, pruned_at=NOW)
    with pytest.raises(ValueError, match="unavailable"):
        resolver.resolve_media(resolver.media_inputs[0])


def _reference() -> SessionAttachmentRef:
    return SessionAttachmentRef(
        attachment_id=new_artifact_id(),
        message_event_id=new_event_id(),
        file_name="review.png",
        media_type="image/png",
        size_bytes=len(IMAGE),
        sha256=sha256(IMAGE).hexdigest(),
        storage_kind="task_workspace",
        workspace_path="images/review.png",
    )


def _payload(session_id: SessionId) -> ArtifactPayloadWrite:
    return ArtifactPayloadWrite(
        session_id=session_id,
        kind="user_attachment",
        mime_type="image/png",
        payload=IMAGE,
        file_name="review.png",
        created_at=NOW,
    )
