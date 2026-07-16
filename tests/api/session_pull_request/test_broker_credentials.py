from pathlib import Path

import pytest
from agent_storage import SQLiteDeliveryAuditStore
from pull_request_support import (
    _allow_github_egress,
    _FakeGitHubTransport,
    _git_workspace,
    _github_app_broker,
    _github_broker,
    _github_scm,
    _seed_ready_session,
    _settings,
)
from zebra_agent_api.app import create_app


def test_api_pull_request_uses_broker_credential_for_github_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_github_egress(monkeypatch)
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")

    response = create_app(
        database_path,
        settings=_settings(None, scm=_github_scm(pull_request_dry_run=False)),
        credential_broker=_github_broker(env={"GITHUB_TOKEN": "broker-token"}),
        github_transport=transport,
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    pull_request = response.body["pull_request"]
    assert pull_request["provider"] == "github"
    assert pull_request["status"] == "created"
    assert pull_request["url"] == "https://github.example/pulls/1"
    assert pull_request["credential_source"] == "broker"
    assert pull_request["credential_backend"] == "environment"
    assert transport.token == "broker-token"
    assert "broker-token" not in repr(response.body)
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "created"
    assert audit_records[0].result_metadata["provider"] == "github"
    assert audit_records[0].result_metadata["dry_run"] is False
    assert audit_records[0].result_metadata["url"] == "https://github.example/pulls/1"
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert "broker-token" not in repr(audit_records[0].result_metadata)

def test_api_pull_request_uses_default_environment_broker_for_github_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_github_egress(monkeypatch)
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")

    response = create_app(
        database_path,
        settings=_settings(None, scm=_github_scm(pull_request_dry_run=False)),
        credential_env={"ZEBRA_TEST_MISSING_GITHUB_TOKEN": "default-broker-token"},
        github_transport=transport,
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    assert response.body["pull_request"]["status"] == "created"
    assert response.body["pull_request"]["credential_source"] == "broker"
    assert response.body["pull_request"]["credential_backend"] == "environment"
    assert transport.token == "default-broker-token"
    assert "default-broker-token" not in repr(response.body)
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"

def test_api_pull_request_uses_github_app_broker_for_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_github_egress(monkeypatch)
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")

    response = create_app(
        database_path,
        settings=_settings(None, scm=_github_scm(pull_request_dry_run=False)),
        credential_broker=_github_app_broker(tmp_path),
        github_transport=transport,
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    assert response.body["pull_request"]["credential_source"] == "broker"
    assert response.body["pull_request"]["credential_backend"] == "github_app"
    assert transport.token == "github-app-token"
    assert "private-key-material" not in repr(response.body)
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "github_app"
    assert "private-key-material" not in repr(audit_records[0].result_metadata)
