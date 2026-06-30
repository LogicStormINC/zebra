import base64
from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.sessions import Session
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteDeliveryAuditStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
    SQLiteWorkspaceProjectionStore,
)
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_api_get_session_artifacts_returns_indexed_artifacts(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)

    response = create_app(database_path).get_session_artifacts(str(session.session_id))

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert response.body["artifacts"] == [
        {
            "artifact_id": "model-call:4",
            "sequence": 4,
            "source": "model_call",
            "kind": "assistant_message",
            "label": "deepseek-v4-flash",
            "uri": None,
            "preview": "Summarized the repository.",
            "preview_state": {
                "redacted": False,
                "truncated": False,
            },
            "metadata": {
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "latency_ms": 250,
                "cache_hit": False,
                "cost_usd": 0.001,
                "tool_call_count": 1,
                "created_at": _created_at().isoformat(),
            },
            "retrieval": {
                "status": "indexed_only",
                "retrievable": False,
                "uri": None,
            },
            "lifecycle": None,
            "access": {
                "class": "operator_safe",
                "required_policy_profile": "workspace_write",
                "session_policy_profile": "workspace_write",
                "allowed": True,
            },
        },
        {
            "artifact_id": "tool-run:5",
            "sequence": 5,
            "source": "tool_run",
            "kind": "tool_output",
            "label": "tests.run",
            "uri": "file:///tmp/pytest.log",
            "preview": "pytest passed",
            "preview_state": {
                "redacted": False,
                "truncated": False,
            },
            "metadata": {
                "tool_name": "tests.run",
                "status": "executed",
                "idempotency_key": "tool-5",
                "created_at": _created_at().isoformat(),
            },
            "retrieval": {
                "status": "payload_missing",
                "retrievable": False,
                "uri": "file:///tmp/pytest.log",
            },
            "lifecycle": None,
            "access": {
                "class": "sensitive",
                "required_policy_profile": "full_access",
                "session_policy_profile": "workspace_write",
                "allowed": False,
            },
        },
    ]


def test_api_get_session_artifacts_returns_empty_list(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)

    response = create_app(database_path).get_session_artifacts(str(session.session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session.session_id),
        "artifacts": [],
    }


def test_api_get_session_artifacts_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_artifacts(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_route_adapter_handles_session_artifacts(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session.session_id}/artifacts")
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert len(response.body["artifacts"]) == 2


def test_api_get_session_artifact_detail_distinguishes_indexed_and_payload_backed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        retained_until=datetime(2099, 6, 30, 14, 0, tzinfo=UTC),
    )

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 200
    assert response.body["status"] == "ok"
    assert response.body["artifact"]["uri"] == payload.uri
    assert response.body["artifact"]["preview_state"] == {
        "redacted": False,
        "truncated": False,
    }
    assert response.body["artifact"]["retrieval"] == {
        "status": "payload_available",
        "retrievable": True,
        "uri": payload.uri,
    }
    assert response.body["artifact"]["lifecycle"] == {
        "status": "active",
        "retained_until": datetime(2099, 6, 30, 14, 0, tzinfo=UTC).isoformat(),
        "pruned_at": None,
        "expired": False,
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].action == "session.artifact.detail"
    assert audit[-1].result_metadata["artifact_id"] == "tool-run:5"
    assert audit[-1].result_metadata["retrieval_status"] == "payload_available"


def test_api_get_session_artifact_detail_reports_indexed_only(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "model-call:4",
    )

    assert response.status_code == 200
    assert response.body["status"] == "ok"
    assert response.body["artifact"]["retrieval"] == {
        "status": "indexed_only",
        "retrievable": False,
        "uri": None,
    }
    assert response.body["artifact"]["lifecycle"] is None


def test_api_get_session_artifacts_includes_lifecycle_for_payload_backed_artifacts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        retained_until=datetime(2099, 6, 30, 13, 0, tzinfo=UTC),
    )

    response = create_app(database_path).get_session_artifacts(str(session.session_id))

    assert response.status_code == 200
    tool_artifact = response.body["artifacts"][0]
    assert tool_artifact["lifecycle"] == {
        "status": "active",
        "retained_until": datetime(2099, 6, 30, 13, 0, tzinfo=UTC).isoformat(),
        "pruned_at": None,
        "expired": False,
    }


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
    Path(payload.uri.removeprefix("file://")).unlink()

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
    assert response.body["status"] == "pruned"
    assert response.body["access_class"] == "operator_safe"
    assert response.body["required_policy_profile"] == "workspace_write"
    assert response.body["lifecycle"]["status"] == "pruned"
    assert response.body["lifecycle"]["pruned_at"] is not None
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


def _seed_session(database_path: Path) -> Session:
    return SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Artifact session")
    )


def _seed_artifacts(database_path: Path, session_id: SessionId) -> None:
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
            created_at=_created_at(),
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
            artifact_uri="file:///tmp/pytest.log",
            created_at=_created_at(),
        )
    )


def _seed_payload_backed_tool_artifact(
    database_path: Path,
    session_id: SessionId,
    *,
    mime_type: str = "text/plain",
    payload: bytes = b"pytest passed",
    output: str = "pytest passed",
    file_name: str = "pytest.log",
    retained_until: datetime | None = None,
):
    payload = SQLiteArtifactPayloadStore(database_path).store_payload(
        ArtifactPayloadWrite(
            session_id=session_id,
            kind="tool_output",
            mime_type=mime_type,
            payload=payload,
            file_name=file_name,
            retained_until=retained_until,
            created_at=_created_at(),
        )
    )
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output=output,
            artifact_uri=payload.uri,
            created_at=_created_at(),
        )
    )
    return payload


def _seed_workspace_policy(
    database_path: Path,
    session_id: SessionId,
    policy_profile: str,
) -> None:
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection(
            session_id=session_id,
            workspace_root="/tmp/workspace",
            prepared_at=_created_at(),
            updated_at=_created_at(),
            current_sequence=1,
            status=WorkspaceStatus.PREPARED,
            policy_profile=policy_profile,
        )
    )


def _created_at() -> datetime:
    return datetime(2026, 6, 23, 14, 0, tzinfo=UTC)


def _settings(auth_token: str | None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
