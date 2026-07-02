from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteArtifactStore,
    SQLiteModelCallStore,
    SQLiteToolRunStore,
    artifact_content_unavailable_reason,
    lifecycle_for_artifact_uri,
    payload_for_artifact_uri,
    resolve_payload_for_artifact_uri,
    serialize_artifact_lifecycle,
    serialize_artifact_retrieval,
    serialize_session_artifact_projection,
)


def test_payload_for_artifact_uri_returns_stored_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "projection.db"
    payload_store = SQLiteArtifactPayloadStore(database_path)
    stored = payload_store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool_output",
            mime_type="text/plain",
            payload=b"pytest passed\n",
            file_name="pytest.log",
            created_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
    )

    resolved = payload_for_artifact_uri(payload_store, stored.uri)

    assert resolved == stored


def test_resolve_payload_for_artifact_uri_returns_stored_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "projection.db"
    payload_store = SQLiteArtifactPayloadStore(database_path)
    stored = payload_store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool_output",
            mime_type="text/plain",
            payload=b"pytest passed\n",
            file_name="pytest.log",
            created_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
    )

    resolved = resolve_payload_for_artifact_uri(database_path, stored.uri)

    assert resolved == stored


def test_serialize_artifact_lifecycle_marks_expired_active_payload(tmp_path: Path) -> None:
    payload_store = SQLiteArtifactPayloadStore(tmp_path / "projection.db")
    stored = payload_store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool_output",
            mime_type="text/plain",
            payload=b"expired\n",
            retained_until=datetime(2026, 6, 30, 11, 0, tzinfo=UTC),
            created_at=datetime(2026, 6, 30, 10, 0, tzinfo=UTC),
        )
    )

    lifecycle = serialize_artifact_lifecycle(
        stored,
        now=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    assert lifecycle == {
        "status": "active",
        "retained_until": datetime(2026, 6, 30, 11, 0, tzinfo=UTC).isoformat(),
        "pruned_at": None,
        "expired": True,
    }


def test_serialize_artifact_retrieval_reports_pruned_payload(tmp_path: Path) -> None:
    payload_store = SQLiteArtifactPayloadStore(tmp_path / "projection.db")
    stored = payload_store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool_output",
            mime_type="text/plain",
            payload=b"pytest passed\n",
            created_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
    )
    pruned = payload_store.prune_payload(
        stored.artifact_id,
        pruned_at=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
    )
    assert pruned is not None

    retrieval = serialize_artifact_retrieval(
        stored.uri,
        lifecycle=serialize_artifact_lifecycle(pruned),
    )

    assert retrieval == {
        "status": "payload_pruned",
        "retrievable": False,
        "uri": stored.uri,
    }


def test_lifecycle_for_artifact_uri_uses_shared_payload_lookup(tmp_path: Path) -> None:
    database_path = tmp_path / "projection.db"
    payload_store = SQLiteArtifactPayloadStore(database_path)
    stored = payload_store.store_payload(
        ArtifactPayloadWrite(
            session_id=new_session_id(),
            kind="tool_output",
            mime_type="text/plain",
            payload=b"pytest passed\n",
            created_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
    )

    lifecycle = lifecycle_for_artifact_uri(
        payload_store,
        stored.uri,
        now=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    assert lifecycle == {
        "status": "active",
        "retained_until": None,
        "pruned_at": None,
        "expired": False,
    }


def test_artifact_content_unavailable_reason_maps_shared_status_values() -> None:
    assert artifact_content_unavailable_reason("indexed_only") == "artifact_is_indexed_only"
    assert (
        artifact_content_unavailable_reason("external_reference")
        == "artifact_uses_external_reference"
    )
    assert artifact_content_unavailable_reason("payload_missing") == "artifact_payload_missing"
    assert artifact_content_unavailable_reason("payload_pruned") == "artifact_payload_pruned"
    assert artifact_content_unavailable_reason("payload_available") is None


def test_serialize_session_artifact_projection_builds_shared_envelope(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "projection.db"
    session_id = new_session_id()
    created_at = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    payload_store = SQLiteArtifactPayloadStore(database_path)
    stored = payload_store.store_payload(
        ArtifactPayloadWrite(
            session_id=session_id,
            kind="tool_output",
            mime_type="text/plain",
            payload=b"pytest passed\n",
            file_name="pytest.log",
            created_at=created_at,
        )
    )
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="pytest passed",
            artifact_uri=stored.uri,
            created_at=created_at,
        )
    )
    artifact = SQLiteArtifactStore(database_path).list_for_session(session_id)[0]
    lifecycle = serialize_artifact_lifecycle(stored, now=created_at)
    retrieval = serialize_artifact_retrieval(stored.uri, lifecycle=lifecycle)

    projection = serialize_session_artifact_projection(
        artifact,
        lifecycle=lifecycle,
        retrieval=retrieval,
    )

    assert projection == {
        "artifact_id": "tool-run:5",
        "sequence": 5,
        "source": "tool_run",
        "kind": "tool_output",
        "label": "tests.run",
        "uri": stored.uri,
        "preview": "pytest passed",
        "preview_state": {"redacted": False, "truncated": False},
        "metadata": {
            "tool_name": "tests.run",
            "status": "executed",
            "idempotency_key": "tool-5",
            "created_at": created_at.isoformat(),
        },
        "retrieval": {
            "status": "payload_available",
            "retrievable": True,
            "uri": stored.uri,
        },
        "lifecycle": {
            "status": "active",
            "retained_until": None,
            "pruned_at": None,
            "expired": False,
        },
    }


def test_serialize_session_artifact_projection_handles_indexed_only_model_artifact(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "projection.db"
    session_id = new_session_id()
    created_at = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    SQLiteModelCallStore(database_path).upsert(
        ModelCallRecord(
            session_id=session_id,
            sequence=4,
            provider="deepseek",
            model_name="deepseek-v4-flash",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            latency_ms=250,
            cache_hit=False,
            cost_usd=0.001,
            assistant_message="Summarized the repository.",
            tool_call_count=1,
            created_at=created_at,
        )
    )
    artifact = SQLiteArtifactStore(database_path).list_for_session(session_id)[0]

    projection = serialize_session_artifact_projection(artifact)

    assert projection["retrieval"] == {
        "status": "indexed_only",
        "retrievable": False,
        "uri": None,
    }
    assert projection["lifecycle"] is None
