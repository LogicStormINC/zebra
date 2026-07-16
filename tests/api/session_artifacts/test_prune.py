from pathlib import Path

from agent_core.domain.tool_runs import ToolRunRecord
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteDeliveryAuditStore,
    SQLiteToolRunStore,
)
from session_artifact_support import (
    _created_at,
    _seed_artifacts,
    _seed_payload_backed_tool_artifact,
    _seed_session,
    _seed_workspace_policy,
)
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_prune_session_artifact_prunes_operator_safe_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)

    response = create_app(database_path).prune_session_artifact(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert response.body["artifact_id"] == "tool-run:5"
    assert response.body["status"] == "pruned"
    assert response.body["access_class"] == "operator_safe"
    assert response.body["required_policy_profile"] == "workspace_write"
    assert response.body["lifecycle"]["status"] == "pruned"
    assert response.body["lifecycle"]["pruned_at"] is not None
    assert response.body["lifecycle"]["retained_until"] is None
    assert response.body["lifecycle"]["expired"] is False
    inspection = SQLiteArtifactPayloadStore(database_path).inspect_payload(payload.artifact_id)
    assert inspection is not None
    assert (
        inspection.status
        == "pruned"
    )
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].action == "session.artifact.prune"
    assert audit[-1].result_metadata["artifact_id"] == "tool-run:5"

def test_api_prune_session_artifact_is_idempotent_for_already_pruned_payload(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)

    first = create_app(database_path).prune_session_artifact(
        str(session.session_id),
        "tool-run:5",
    )
    second = create_app(database_path).prune_session_artifact(
        str(session.session_id),
        "tool-run:5",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.body["status"] == "already_pruned"

def test_api_prune_session_artifact_denies_sensitive_payload_for_workspace_write(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        mime_type="application/json",
        payload=b'{"token":"secret"}',
        output='{"token":"secret"}',
        file_name="result.json",
    )

    response = create_app(database_path).prune_session_artifact(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "artifact_prune_denied",
        "reason": "artifact_prune_requires_full_access_policy",
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].result_metadata["access_class"] == "sensitive"
    assert audit[-1].result_metadata["required_policy_profile"] == "full_access"
    assert audit[-1].result_metadata["session_policy_profile"] == "workspace_write"
    assert audit[-1].result_metadata["result_status"] == "artifact_prune_denied"

def test_api_prune_session_artifact_reports_indexed_only_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)

    response = create_app(database_path).prune_session_artifact(
        str(session.session_id),
        "model-call:4",
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "artifact_prune_unavailable",
        "reason": "artifact_is_indexed_only",
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].result_metadata["result_status"] == "artifact_prune_unavailable"
    assert audit[-1].result_metadata["unavailable_reason"] == "artifact_is_indexed_only"

def test_api_prune_session_artifact_reports_external_reference_unavailable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="see external artifact",
            artifact_uri="https://example.com/result.json",
            created_at=_created_at(),
        )
    )

    response = create_app(database_path).prune_session_artifact(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "artifact_prune_unavailable",
        "reason": "artifact_uses_external_reference",
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].result_metadata["result_status"] == "artifact_prune_unavailable"
    assert audit[-1].result_metadata["unavailable_reason"] == "artifact_uses_external_reference"

def test_route_adapter_handles_session_artifact_prune(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session.session_id}/artifacts/tool-run:5/prune",
            body={},
        )
    )

    assert response.status_code == 200
    assert response.body["status"] == "pruned"
