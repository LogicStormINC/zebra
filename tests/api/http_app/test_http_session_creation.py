from dataclasses import replace
from pathlib import Path

import pytest
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


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("agent_id", "agent-neutral\nUNTRUSTED_SYSTEM_TEXT"),
        ("version", "1.0.0\r\nUNTRUSTED_SYSTEM_TEXT"),
    ),
)
def test_http_create_session_rejects_control_characters_in_definition_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    definition = {
        "agent_id": "agent-neutral",
        "version": "1.0.0",
    }
    definition[field] = value
    client = TestClient(create_http_app(tmp_path / f"{field}.sqlite"))

    response = client.post(
        "/sessions",
        json={
            "prompt": "Inspect the workspace",
            "agent_definition": definition,
        },
    )

    assert response.status_code == 400


def test_http_create_session_accepts_existing_definition_identity(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions",
        json={
            "prompt": "Inspect the workspace",
            "agent_definition": {
                "agent_id": "agent-neutral",
                "version": "1.0.0",
            },
        },
    )

    assert response.status_code == 201
    assert response.json()["agent_definition"] == {
        "agent_id": "agent-neutral",
        "version": "1.0.0",
        "system_prompt_ref": None,
        "skill_refs": [],
        "required_model_capabilities": [],
        "capability_policy": {},
        "memory_policy": {},
        "trust_policy": {},
        "eval_suite_ref": None,
        "completion_contract": {"version": "1", "required_evidence": []},
    }


def test_local_http_app_persists_trusted_network_for_new_tasks(tmp_path: Path) -> None:
    settings = replace(_settings(None), profile="local")
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite", settings=settings))

    response = client.post(
        "/tasks",
        json={
            "prompt": "Inspect the workspace",
            "title": "Trusted local task",
            "network_profile": "none",
        },
    )

    assert response.status_code == 201
    assert response.json()["network_profile"] == "full-trusted-local"


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
    body = response.json()
    assert body["final_message"] == {
        "message_id": body["final_message"]["message_id"],
        "cursor": body["final_message"]["cursor"],
    }
    assert body["artifact_output_contract"] is None
    assert {
        key: value
        for key, value in body.items()
        if key not in {"final_message", "artifact_output_contract"}
    } == {
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
    assert body["final_message"]["cursor"] == 5
    assert body["final_message"]["message_id"].startswith("final:")


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
