import base64
from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.sessions import Session
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
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
        },
        {
            "artifact_id": "tool-run:5",
            "sequence": 5,
            "source": "tool_run",
            "kind": "tool_output",
            "label": "tests.run",
            "uri": "file:///tmp/pytest.log",
            "preview": "pytest passed",
            "metadata": {
                "tool_name": "tests.run",
                "status": "executed",
                "idempotency_key": "tool-5",
                "created_at": _created_at().isoformat(),
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
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 200
    assert response.body["artifact"]["uri"] == payload.uri
    assert response.body["artifact"]["retrieval"] == {
        "status": "payload_available",
        "retrievable": True,
        "uri": payload.uri,
    }


def test_api_get_session_artifact_detail_reports_indexed_only(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "model-call:4",
    )

    assert response.status_code == 200
    assert response.body["artifact"]["retrieval"] == {
        "status": "indexed_only",
        "retrievable": False,
        "uri": None,
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
    }


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


def _seed_payload_backed_tool_artifact(database_path: Path, session_id: SessionId):
    payload = SQLiteArtifactPayloadStore(database_path).store_payload(
        ArtifactPayloadWrite(
            session_id=session_id,
            kind="tool_output",
            mime_type="text/plain",
            payload=b"pytest passed",
            file_name="pytest.log",
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
            artifact_uri=payload.uri,
            created_at=_created_at(),
        )
    )
    return payload


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
