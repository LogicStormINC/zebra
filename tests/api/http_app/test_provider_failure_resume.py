"""Gate A red: resume HTTP stays bounded for both provider classifications."""

from pathlib import Path
from uuid import UUID

import zebra_agent_worker.execution as worker_execution_module
from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_integrations.model_errors import ModelProviderError
from agent_storage import SQLiteProjectionStore
from fastapi.testclient import TestClient
from http_app_support import _seed_ready_session, _settings
from zebra_agent_api import create_http_app


def _rejecting_provider_gateway(settings):
    class RejectingGateway:
        def complete(self, messages, *, tools=()) -> ModelCompletion:
            raise AssertionError("streaming path expected")

        def complete_stream(self, messages, *, tools=(), on_text_delta) -> ModelCompletion:
            raise ModelProviderError("content_filtered", retryable=False, retry_count=0)

    return RejectingGateway()


def test_http_app_provider_failure_resume_returns_durable_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _rejecting_provider_gateway)
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings(None)))

    response = client.post(f"/sessions/{session_id}/resume", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    session = SQLiteProjectionStore(database_path).get_session(SessionId(UUID(session_id)))
    assert session is not None
    assert session.status is SessionStatus.FAILED

    second = client.post(f"/sessions/{session_id}/resume", json={})
    assert second.status_code == 409
    assert second.json()["status"] == "not_resumable"


def _retryable_provider_gateway(settings):
    class RetryableGateway:
        def complete(self, messages, *, tools=()) -> ModelCompletion:
            raise AssertionError("streaming path expected")

        def complete_stream(self, messages, *, tools=(), on_text_delta) -> ModelCompletion:
            raise ModelProviderError("provider_error", retryable=True, retry_count=0)

    return RetryableGateway()


def test_http_app_retryable_provider_failure_suspends_and_resumes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        worker_execution_module,
        "build_model_gateway",
        _retryable_provider_gateway,
    )
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings(None)))

    first = client.post(f"/sessions/{session_id}/resume", json={})

    assert first.status_code == 200
    assert first.json()["status"] == "suspended"
    session = SQLiteProjectionStore(database_path).get_session(SessionId(UUID(session_id)))
    assert session is not None
    assert session.status is SessionStatus.SUSPENDED

    from http_app_support import _fake_resume_gateway

    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _fake_resume_gateway)
    second = client.post(f"/sessions/{session_id}/resume", json={})
    assert second.status_code == 200
    assert second.json()["status"] == "completed"
