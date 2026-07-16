from pathlib import Path

import pytest
from agent_integrations import (
    GitHubProxyPullRequestTransport,
)
from agent_storage import SQLiteDeliveryAuditStore
from pull_request_support import (
    _allow_github_egress,
    _denied_github_broker,
    _FailingGitHubAppTransport,
    _FailingGitHubTransport,
    _FailingScmProxyTransport,
    _FakeGitHubTransport,
    _FakeScmProxyTransport,
    _git_workspace,
    _github_app_broker,
    _github_broker,
    _github_scm,
    _seed_ready_session,
    _settings,
    _unavailable_github_broker,
)
from zebra_agent_api.app import create_app


def test_api_pull_request_missing_broker_credential_records_audit(
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
        credential_broker=_github_broker(env={}),
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

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "pull_request_unavailable",
        "reason": "credential environment value is missing",
        "idempotency_key": None,
    }
    assert transport.token is None
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "pull_request_unavailable"
    assert audit_records[0].result_metadata["provider"] == "github"
    assert audit_records[0].result_metadata["dry_run"] is False
    assert audit_records[0].result_metadata["reason"] == ("credential environment value is missing")
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert audit_records[0].result_metadata["failure_class"] == "credential_missing"

def test_api_pull_request_missing_default_broker_credential_records_audit(
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
        credential_env={},
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

    assert response.status_code == 409
    assert response.body["status"] == "pull_request_unavailable"
    assert response.body["reason"] == "credential environment value is missing"
    assert transport.token is None
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["provider"] == "github"
    assert audit_records[0].result_metadata["dry_run"] is False
    assert audit_records[0].result_metadata["reason"] == ("credential environment value is missing")
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert audit_records[0].result_metadata["failure_class"] == "credential_missing"

def test_api_pull_request_denied_broker_credential_records_audit(
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
        credential_broker=_denied_github_broker(),
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

    assert response.status_code == 409
    assert response.body["status"] == "pull_request_unavailable"
    assert response.body["reason"] == "credential request denied for audience"
    assert transport.token is None
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert audit_records[0].result_metadata["failure_class"] == "credential_denied"

def test_api_pull_request_unavailable_broker_records_audit(
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
        credential_broker=_unavailable_github_broker(),
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

    assert response.status_code == 409
    assert response.body["status"] == "pull_request_unavailable"
    assert response.body["reason"] == "credential broker is unavailable"
    assert transport.token is None
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert audit_records[0].result_metadata["failure_class"] == "credential_unavailable"

def test_api_pull_request_transport_failure_records_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_github_egress(monkeypatch)
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(
        database_path,
        settings=_settings(None, scm=_github_scm(pull_request_dry_run=False)),
        credential_broker=_github_broker(env={"GITHUB_TOKEN": "broker-token"}),
        github_transport=_FailingGitHubTransport(),
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
    )

    assert response.status_code == 409
    assert response.body["status"] == "pull_request_unavailable"
    assert response.body["reason"] == "github pull request execution failed: transport offline"
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert audit_records[0].result_metadata["failure_class"] == "transport_failure"

def test_api_pull_request_uses_proxy_transport_for_github_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_github_egress(monkeypatch)
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    proxy_transport = _FakeScmProxyTransport(url="https://github.example/pulls/2")

    response = create_app(
        database_path,
        settings=_settings(None, scm=_github_scm(pull_request_dry_run=False)),
        credential_broker=_github_broker(env={"GITHUB_TOKEN": "broker-token"}),
        github_transport=GitHubProxyPullRequestTransport(proxy_transport=proxy_transport),
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
    assert response.body["pull_request"]["url"] == "https://github.example/pulls/2"
    assert response.body["pull_request"]["route"] == "proxy"
    assert response.body["pull_request"]["proxy_target"] == "github.pull_request.create"
    assert response.body["pull_request"]["proxy_transport"] == "scm_http_proxy"
    assert proxy_transport.last_request is not None
    assert proxy_transport.last_request.provider == "github"
    assert "broker-token" not in repr(proxy_transport.last_request.to_serializable())
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert audit_records[0].result_metadata["route"] == "proxy"
    assert audit_records[0].result_metadata["proxy_target"] == "github.pull_request.create"
    assert audit_records[0].result_metadata["proxy_transport"] == "scm_http_proxy"

def test_api_pull_request_proxy_transport_failure_records_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_github_egress(monkeypatch)
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(
        database_path,
        settings=_settings(None, scm=_github_scm(pull_request_dry_run=False)),
        credential_broker=_github_broker(env={"GITHUB_TOKEN": "broker-token"}),
        github_transport=GitHubProxyPullRequestTransport(
            proxy_transport=_FailingScmProxyTransport()
        ),
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
    )

    assert response.status_code == 409
    assert response.body["status"] == "pull_request_unavailable"
    assert response.body["reason"] == "scm proxy execution failed: proxy offline"
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"
    assert audit_records[0].result_metadata["failure_class"] == "transport_failure"

def test_api_pull_request_github_app_transport_failure_records_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_github_egress(monkeypatch)
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(
        database_path,
        settings=_settings(None, scm=_github_scm(pull_request_dry_run=False)),
        credential_broker=_github_app_broker(
            tmp_path,
            app_transport=_FailingGitHubAppTransport(),
        ),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
    )

    assert response.status_code == 409
    assert response.body["status"] == "pull_request_unavailable"
    assert response.body["reason"] == "github app token exchange failed"
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "github_app"
    assert audit_records[0].result_metadata["failure_class"] == "transport_failure"
