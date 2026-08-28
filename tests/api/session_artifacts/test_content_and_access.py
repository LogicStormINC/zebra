import base64
from pathlib import Path

from agent_core.domain.tool_runs import ToolRunRecord
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteDeliveryAuditStore,
    SQLiteToolRunStore,
)
from fastapi.testclient import TestClient
from session_artifact_support import (
    _created_at,
    _seed_payload_backed_tool_artifact,
    _seed_session,
    _seed_workspace_policy,
    _settings,
)
from zebra_agent_api import create_http_app
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_get_session_artifact_content_returns_payload_bytes(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)

    response = create_app(database_path).get_session_artifact_content(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "status": "ok",
        "access": {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "workspace_write",
            "allowed": True,
        },
        "encoding": "base64",
        "content_base64": base64.b64encode(b"pytest passed").decode("ascii"),
        "size_bytes": 13,
    }
    assert payload.uri is not None

def test_api_get_session_artifact_content_reports_missing_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)
    Path(payload.access_uri.removeprefix("file://")).unlink()

    response = create_app(database_path).get_session_artifact_content(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "artifact_unavailable",
        "reason": "artifact_payload_missing",
        "access": {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "workspace_write",
            "allowed": True,
        },
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].action == "session.artifact.content"
    assert audit[-1].result_metadata["artifact_id"] == "tool-run:5"
    assert audit[-1].result_metadata["access_class"] == "operator_safe"
    assert audit[-1].result_metadata["retrieval_status"] == "payload_missing"

def test_api_get_session_artifact_content_reports_pruned_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)
    SQLiteArtifactPayloadStore(database_path).prune_payload(payload.artifact_id)

    response = create_app(database_path).get_session_artifact_content(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "artifact_unavailable",
        "reason": "artifact_payload_pruned",
        "access": {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "workspace_write",
            "allowed": True,
        },
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].result_metadata["retrieval_status"] == "payload_pruned"

def test_api_get_session_artifact_detail_redacts_sensitive_preview(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.FULL_ACCESS.value)
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="api_key=secret-value " + ("x" * 200),
            artifact_uri=None,
            created_at=_created_at(),
        )
    )

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 200
    assert "[REDACTED]" in response.body["artifact"]["preview"]
    assert response.body["artifact"]["preview"].endswith("...")
    assert response.body["artifact"]["preview_state"] == {
        "redacted": True,
        "truncated": True,
    }

def test_api_get_session_artifact_detail_denies_sensitive_payload_for_workspace_write(
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

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "artifact_access_denied",
        "reason": "artifact_read_requires_full_access_policy",
        "access": {
            "class": "sensitive",
            "required_policy_profile": "full_access",
            "session_policy_profile": "workspace_write",
            "allowed": False,
        },
    }

def test_api_get_session_artifact_content_denies_sensitive_payload_for_workspace_write(
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

    response = create_app(database_path).get_session_artifact_content(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "artifact_access_denied",
        "reason": "artifact_read_requires_full_access_policy",
        "access": {
            "class": "sensitive",
            "required_policy_profile": "full_access",
            "session_policy_profile": "workspace_write",
            "allowed": False,
        },
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].result_metadata == {
        "reason": "artifact_read_requires_full_access_policy",
        "artifact_id": "tool-run:5",
        "access_class": "sensitive",
        "required_policy_profile": "full_access",
        "session_policy_profile": "workspace_write",
        "result_status": "artifact_access_denied",
        "retrieval_status": "access_denied",
    }

def test_api_get_session_artifact_content_allows_sensitive_payload_for_full_access(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.FULL_ACCESS.value)
    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        mime_type="application/json",
        payload=b'{"token":"secret"}',
        output='{"token":"secret"}',
        file_name="result.json",
    )

    response = create_app(database_path).get_session_artifact_content(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 200
    assert response.body["artifact_id"] == "tool-run:5"

def test_http_app_session_artifacts_requires_bearer_token_when_configured(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(f"/sessions/{session.session_id}/artifacts")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }

def test_route_adapter_handles_session_artifact_content(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="GET",
            path=f"/sessions/{session.session_id}/artifacts/tool-run:5/content",
        )
    )

    assert response.status_code == 200
    assert response.body["artifact_id"] == "tool-run:5"


def test_http_download_returns_raw_private_attachment(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)
    client = TestClient(create_http_app(database_path))

    response = client.get(
        f"/tasks/{session.session_id}/artifacts/tool-run:5/download"
    )

    assert response.status_code == 200
    assert response.content == b"pytest passed"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
