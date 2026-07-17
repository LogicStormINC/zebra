from pathlib import Path

import zebra_agent_api.app as api_app_module
import zebra_agent_worker.execution as worker_execution_module
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from fastapi.testclient import TestClient
from http_app_support import (
    _created_at,
    _fake_resume_gateway,
    _seed_ready_session,
    _settings,
)
from zebra_agent_api import create_http_app
from zebra_agent_config import ZebraAgentSettings


def test_http_app_creates_session(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions",
        json={
            "prompt": "Inspect the workspace",
            "title": "HTTP create session",
        },
    )

    assert response.status_code == 201
    assert response.json()["executed"] is False
    assert response.json()["title"] == "HTTP create session"

def test_http_app_executes_session_create(tmp_path: Path, monkeypatch) -> None:

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="HTTP execution complete.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite", settings=_settings("secret")))

    response = client.post(
        "/sessions",
        headers={"Authorization": "Bearer secret"},
        json={
            "prompt": "Inspect the workspace",
            "title": "HTTP execute session",
            "workspace": str(tmp_path),
            "execute": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["executed"] is True
    assert response.json()["assistant_message"] == "HTTP execution complete."

def test_http_app_executes_session_create_reports_missing_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_build_model_gateway(_: ZebraAgentSettings) -> object:
        del _
        raise ValueError("missing API key in environment variable TEST_API_KEY")

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions",
        json={
            "prompt": "Inspect the workspace",
            "title": "HTTP execute session",
            "workspace": str(tmp_path),
            "execute": True,
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "model_gateway_unavailable",
        "reason": "missing API key in environment variable TEST_API_KEY",
    }

def test_http_app_executes_session_resume_reports_missing_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_build_model_gateway(_: ZebraAgentSettings) -> object:
        del _
        raise ValueError("missing API key in environment variable DEEPSEEK_API_KEY")

    monkeypatch.setattr(worker_execution_module, "build_model_gateway", fake_build_model_gateway)
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(f"/sessions/{session_id}/resume", json={})

    assert response.status_code == 503
    assert response.json() == {
        "status": "model_gateway_unavailable",
        "reason": "missing API key in environment variable DEEPSEEK_API_KEY",
    }

def test_http_app_executes_session_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _fake_resume_gateway)
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(
        f"/sessions/{session_id}/resume",
        headers={"Authorization": "Bearer secret"},
        json={"worker_id": "api-worker", "lease_ttl_seconds": 45},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session_id,
        "executed": True,
        "worker_id": "api-worker",
        "status": "completed",
        "current_sequence": 7,
        "assistant_message": "HTTP resume complete.",
        "trace": [
            {
                "attempt_number": 1,
                "assistant_message": "HTTP resume complete.",
                "tools": [],
            }
        ],
    }

def test_http_app_suspends_and_then_resumes_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _fake_resume_gateway)
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before suspend\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace_root=workspace)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    suspend = client.post(
        f"/sessions/{session_id}/suspend",
        headers={"Authorization": "Bearer secret"},
        json={},
    )
    (workspace / "note.txt").write_text("after suspend\n", encoding="utf-8")
    resume = client.post(
        f"/sessions/{session_id}/resume",
        headers={"Authorization": "Bearer secret"},
        json={"worker_id": "api-worker", "lease_ttl_seconds": 45},
    )

    assert suspend.status_code == 200
    assert suspend.json()["status"] == "suspended"
    assert resume.status_code == 200
    assert resume.json()["status"] == "completed"
