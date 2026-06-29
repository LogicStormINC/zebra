from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadStatus, ArtifactPayloadWrite
from agent_core.domain.identifiers import new_artifact_id, new_session_id
from agent_storage import ArtifactPayloadMissingError, SQLiteArtifactPayloadStore


def test_sqlite_artifact_payload_store_persists_metadata_and_bytes(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    payload = ArtifactPayloadWrite(
        session_id=new_session_id(),
        kind="tool-output-log",
        mime_type="text/plain",
        payload=b"pytest passed\n",
        file_name="pytest.log",
        created_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
    )

    stored = store.store_payload(payload)
    reloaded = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db").get_payload(stored.artifact_id)

    assert reloaded is not None
    assert reloaded.artifact_id == stored.artifact_id
    assert reloaded.kind == "tool-output-log"
    assert reloaded.mime_type == "text/plain"
    assert reloaded.size_bytes == len(payload.payload)
    assert reloaded.sha256 == stored.sha256
    assert Path(reloaded.uri.removeprefix("file://")).is_file()
    assert store.read_payload_bytes(stored.artifact_id) == b"pytest passed\n"


def test_sqlite_artifact_payload_store_reports_missing_file_explicitly(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    stored = store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="assistant-artifact",
            mime_type="application/json",
            payload=b'{"ok": true}',
            file_name="result.json",
            created_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        )
    )
    payload_path = Path(stored.uri.removeprefix("file://"))
    payload_path.unlink()

    inspection = store.inspect_payload(stored.artifact_id)

    assert inspection is not None
    assert inspection.status is ArtifactPayloadStatus.MISSING
    with pytest.raises(ArtifactPayloadMissingError, match="file is missing"):
        store.read_payload_bytes(stored.artifact_id)


def test_sqlite_artifact_payload_store_returns_none_for_unknown_artifact(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")

    unknown_artifact_id = new_artifact_id()

    assert store.get_payload(unknown_artifact_id) is None
    assert store.inspect_payload(unknown_artifact_id) is None
    with pytest.raises(ArtifactPayloadMissingError, match="metadata was not found"):
        store.read_payload_bytes(unknown_artifact_id)
