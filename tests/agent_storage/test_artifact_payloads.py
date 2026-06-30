from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.artifact_payloads import (
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadStatus,
    ArtifactPayloadWrite,
)
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
    assert reloaded.lifecycle_status is ArtifactPayloadLifecycleStatus.ACTIVE
    assert reloaded.pruned_at is None
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


def test_sqlite_artifact_payload_store_marks_pruned_payload_explicitly(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    stored = store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool-output-log",
            mime_type="text/plain",
            payload=b"pytest passed\n",
            retained_until=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            created_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
    )

    pruned = store.prune_payload(
        stored.artifact_id,
        pruned_at=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
    )
    inspection = store.inspect_payload(stored.artifact_id)

    assert pruned is not None
    assert pruned.lifecycle_status is ArtifactPayloadLifecycleStatus.PRUNED
    assert pruned.retained_until == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert pruned.pruned_at == datetime(2026, 6, 30, 13, 0, tzinfo=UTC)
    assert inspection is not None
    assert inspection.status is ArtifactPayloadStatus.PRUNED
    with pytest.raises(ArtifactPayloadMissingError, match="has been pruned"):
        store.read_payload_bytes(stored.artifact_id)


def test_sqlite_artifact_payload_store_prune_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    stored = store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool-output-log",
            mime_type="text/plain",
            payload=b"pytest passed\n",
            created_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
    )

    first = store.prune_payload(
        stored.artifact_id,
        pruned_at=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
    )
    second = store.prune_payload(
        stored.artifact_id,
        pruned_at=datetime(2026, 6, 30, 14, 0, tzinfo=UTC),
    )

    assert first is not None
    assert second is not None
    assert second.pruned_at == datetime(2026, 6, 30, 13, 0, tzinfo=UTC)


def test_sqlite_artifact_payload_store_sweeps_only_expired_payloads(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    expired = store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool-output-log",
            mime_type="text/plain",
            payload=b"expired\n",
            retained_until=datetime(2026, 6, 30, 11, 0, tzinfo=UTC),
            created_at=datetime(2026, 6, 30, 10, 0, tzinfo=UTC),
        )
    )
    retained = store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool-output-log",
            mime_type="text/plain",
            payload=b"retained\n",
            retained_until=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
            created_at=datetime(2026, 6, 30, 10, 0, tzinfo=UTC),
        )
    )

    swept = store.sweep_expired_payloads(
        as_of=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    assert [payload.artifact_id for payload in swept] == [expired.artifact_id]
    assert store.inspect_payload(expired.artifact_id) is not None
    assert store.inspect_payload(expired.artifact_id).status is ArtifactPayloadStatus.PRUNED
    assert store.inspect_payload(retained.artifact_id) is not None
    assert store.inspect_payload(retained.artifact_id).status is ArtifactPayloadStatus.AVAILABLE


def test_sqlite_artifact_payload_store_returns_none_for_unknown_artifact(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")

    unknown_artifact_id = new_artifact_id()

    assert store.get_payload(unknown_artifact_id) is None
    assert store.inspect_payload(unknown_artifact_id) is None
    with pytest.raises(ArtifactPayloadMissingError, match="metadata was not found"):
        store.read_payload_bytes(unknown_artifact_id)
