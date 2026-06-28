import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_integrations import (
    GitHubAppCredentialBinding,
    GitHubAppCredentialBroker,
    GitHubAppInstallationToken,
    GitHubAppTokenTransport,
    GitHubProxyPullRequestTransport,
    GitHubPullRequestPayload,
    ScmProxyRequest,
    ScmProxyResponse,
    ScmUnavailableError,
)
from agent_security import (
    CredentialBroker,
    CredentialCapability,
    EnvironmentCredentialBinding,
    EnvironmentCredentialBroker,
    InMemoryCredentialBroker,
    LocalSecretStore,
)
from agent_storage import SQLiteDeliveryAuditStore, SQLiteEventStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ApiSettings, ModelSettings, ScmSettings, ZebraAgentSettings


def test_api_pull_request_returns_local_only_dry_run_plan(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(database_path).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "body": "Implementation details.",
            "base_branch": "main",
        },
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["policy_profile"] == "full_access"
    assert response.body["idempotency_key"] is None
    pull_request = response.body["pull_request"]
    assert isinstance(pull_request, dict)
    assert pull_request["provider"] == "local-only"
    assert pull_request["title"] == "Add feature"
    assert pull_request["body"] == "Implementation details."
    assert pull_request["base_branch"] == "main"
    assert len(str(pull_request["commit_sha"])) == 40
    assert pull_request["dry_run"] is True
    assert pull_request["status"] == "dry_run"
    assert pull_request["url"] is None
    assert pull_request["credential_source"] is None
    assert pull_request["credential_backend"] is None
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].action == "session.pull_request"
    assert audit_records[0].status == "dry_run"
    assert audit_records[0].status_code == 200
    assert audit_records[0].policy_profile == "full_access"
    assert audit_records[0].result_metadata["provider"] == "local-only"
    assert audit_records[0].result_metadata["status"] == "dry_run"
    assert audit_records[0].result_metadata["dry_run"] is True
    assert audit_records[0].result_metadata["credential_source"] is None
    assert audit_records[0].result_metadata["credential_backend"] is None


def test_api_pull_request_rejects_network_execution_in_local_only_mode(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(database_path).open_session_pull_request(
        str(session_id),
        {"title": "Add feature", "dry_run": False},
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "pull_request_unavailable",
        "reason": "pull request execution is unavailable in local-only mode",
        "idempotency_key": None,
    }
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "pull_request_unavailable"
    assert audit_records[0].result_metadata["provider"] == "local-only"
    assert audit_records[0].result_metadata["dry_run"] is False


def test_api_pull_request_selects_github_dry_run_gateway(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(
        database_path, settings=_settings(None, scm=_github_scm(pull_request_dry_run=False))
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "body": "Implementation details.",
            "base_branch": "main",
            "head_branch": "feature/zebra",
        },
    )

    assert response.status_code == 200
    pull_request = response.body["pull_request"]
    assert isinstance(pull_request, dict)
    assert pull_request["provider"] == "github"
    assert pull_request["status"] == "dry_run"
    assert pull_request["credential_source"] is None
    assert pull_request["credential_backend"] is None
    assert pull_request["request_payload"] == {
        "endpoint": "https://api.github.com/repos/octo-org/zebra-agent/pulls",
        "headers": {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        "body": {
            "title": "Add feature",
            "body": "Implementation details.",
            "base": "main",
            "head": "feature/zebra",
            "maintainer_can_modify": True,
            "draft": False,
        },
    }
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "dry_run"
    assert audit_records[0].result_metadata["provider"] == "github"
    assert audit_records[0].result_metadata["status"] == "dry_run"
    assert audit_records[0].result_metadata["dry_run"] is True
    assert audit_records[0].result_metadata["credential_source"] is None
    assert audit_records[0].result_metadata["credential_backend"] is None


def test_api_pull_request_github_non_dry_run_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(
        database_path, settings=_settings(None, scm=_github_scm(pull_request_dry_run=False))
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
        "reason": "github pull request execution is blocked by network profile none",
        "idempotency_key": None,
    }
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "pull_request_unavailable"
    assert audit_records[0].result_metadata["provider"] == "github"
    assert audit_records[0].result_metadata["dry_run"] is False
    assert audit_records[0].result_metadata["reason"] == (
        "github pull request execution is blocked by network profile none"
    )
    assert audit_records[0].result_metadata["failure_class"] == "egress_policy"
    assert audit_records[0].result_metadata["network_profile"] == "none"
    assert audit_records[0].result_metadata["target_host"] == "api.github.com"


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
    assert proxy_transport.last_request is not None
    assert proxy_transport.last_request.provider == "github"
    assert "broker-token" not in repr(proxy_transport.last_request.to_serializable())
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].result_metadata["credential_source"] == "broker"
    assert audit_records[0].result_metadata["credential_backend"] == "environment"


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


def test_api_pull_request_rejects_policy_blocked_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="workspace_write")

    response = create_app(database_path).open_session_pull_request(
        str(session_id),
        {"title": "Add feature"},
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "policy_blocked",
        "reason": "pull request requires full_access session policy",
        "idempotency_key": None,
    }
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "policy_blocked"
    assert audit_records[0].policy_profile == "workspace_write"


def test_api_pull_request_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").open_session_pull_request(
        "00000000-0000-0000-0000-000000000001",
        {"title": "Add feature"},
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
        "idempotency_key": None,
    }


def test_api_pull_request_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(database_path).open_session_pull_request(
        str(session_id),
        {"title": "   "},
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "title must be a non-blank string",
    }


def test_route_adapter_handles_session_pull_request(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/pull-request",
            body={"title": "Route PR"},
        )
    )

    assert response.status_code == 200
    assert response.body["pull_request"]["status"] == "dry_run"


def test_api_pull_request_replays_idempotent_response(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    app = create_app(database_path)
    payload = {"title": "Add feature", "base_branch": "main"}

    first_response = app.open_session_pull_request(
        str(session_id),
        payload,
        idempotency_key="pr-key-1",
    )
    replayed_response = app.open_session_pull_request(
        str(session_id),
        payload,
        idempotency_key="pr-key-1",
    )

    assert first_response.status_code == 200
    assert replayed_response.status_code == 200
    assert replayed_response.body == first_response.body
    assert replayed_response.body["idempotency_key"] == "pr-key-1"
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].idempotency_key == "pr-key-1"


def test_api_pull_request_rejects_idempotency_key_reused_for_different_payload(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    app = create_app(database_path)

    app.open_session_pull_request(
        str(session_id),
        {"title": "Add feature", "base_branch": "main"},
        idempotency_key="pr-key-1",
    )
    response = app.open_session_pull_request(
        str(session_id),
        {"title": "Add feature", "base_branch": "develop"},
        idempotency_key="pr-key-1",
    )

    assert response.status_code == 409
    assert response.body == {
        "status": "idempotency_conflict",
        "reason": "idempotency key reused with different request",
    }


def test_route_adapter_forwards_pull_request_idempotency_key(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    adapter = RouteAdapter(create_app(database_path))
    request = RouteRequest(
        method="POST",
        path=f"/sessions/{session_id}/pull-request",
        body={"title": "Route PR"},
        headers={"idempotency-key": "route-pr-1"},
    )

    first_response = adapter.handle(request)
    replayed_response = adapter.handle(request)

    assert first_response.status_code == 200
    assert replayed_response.body == first_response.body
    assert replayed_response.body["idempotency_key"] == "route-pr-1"


def test_http_app_session_pull_request_requires_bearer_token_when_configured(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(
        f"/sessions/{session_id}/pull-request",
        json={"title": "Add feature"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def _seed_ready_session(
    database_path: Path,
    workspace_root: Path,
    *,
    policy_profile: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Pull request session",
            user_input="Open a pull request.",
            workspace_root=workspace_root.resolve(),
            policy_profile=policy_profile,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _git_workspace(path: Path) -> Path:
    path.mkdir()
    _git(path, ("git", "init"))
    _git(path, ("git", "config", "user.name", "Zebra Agent"))
    _git(path, ("git", "config", "user.email", "zebra@example.com"))
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(path, ("git", "add", "tracked.txt"))
    _git(path, ("git", "commit", "-m", "init"))
    return path.resolve()


def _git(path: Path, command: tuple[str, ...]) -> str:
    return run(command, cwd=path, check=True, capture_output=True, text=True).stdout


def _settings(auth_token: str | None, *, scm: ScmSettings | None = None) -> ZebraAgentSettings:
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
        scm=scm or _local_scm(),
    )


def _local_scm() -> ScmSettings:
    return ScmSettings(
        provider="local-only",
        github_owner=None,
        github_repo=None,
        github_token_env=None,
        github_api_base_url="https://api.github.com",
        pull_request_dry_run=True,
    )


def _github_scm(*, pull_request_dry_run: bool = True) -> ScmSettings:
    return ScmSettings(
        provider="github",
        github_owner="octo-org",
        github_repo="zebra-agent",
        github_token_env="ZEBRA_TEST_MISSING_GITHUB_TOKEN",
        github_api_base_url="https://api.github.com",
        pull_request_dry_run=pull_request_dry_run,
    )


def _github_broker(*, env: dict[str, str]) -> EnvironmentCredentialBroker:
    return EnvironmentCredentialBroker(
        bindings=(
            EnvironmentCredentialBinding(
                provider="github",
                audience="repo:octo-org/zebra-agent",
                scopes=("pull_request:create",),
                token_env="GITHUB_TOKEN",
                expires_at=datetime(2026, 7, 23, 12, 30, tzinfo=UTC),
            ),
        ),
        env=env,
    )


def _denied_github_broker() -> CredentialBroker:
    return InMemoryCredentialBroker(
        capabilities=(_github_capability(),),
        denied_audiences=frozenset({"repo:octo-org/zebra-agent"}),
    )


def _unavailable_github_broker() -> InMemoryCredentialBroker:
    return InMemoryCredentialBroker(unavailable=True)


def _github_capability() -> CredentialCapability:
    return CredentialCapability(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create",),
        expires_at=datetime(2026, 7, 23, 12, 30, tzinfo=UTC),
        token_value="broker-token",
    )


def _github_app_broker(
    tmp_path: Path,
    *,
    app_transport: GitHubAppTokenTransport | None = None,
) -> GitHubAppCredentialBroker:
    root = tmp_path / "github-app-secrets"
    secret_path = root / "github" / "app"
    secret_path.mkdir(parents=True, exist_ok=True)
    (secret_path / "private-key.json").write_text(
        json.dumps({"value": "private-key-material", "version": "v1"}),
        encoding="utf-8",
    )
    if app_transport is None:
        app_transport = _FakeGitHubAppTransport()
    return GitHubAppCredentialBroker(
        bindings=(
            GitHubAppCredentialBinding(
                audience="repo:octo-org/zebra-agent",
                installation_id="inst-123",
                app_id="app-123",
                private_key_handle="github/app/private-key",
                scopes=("pull_request:create",),
            ),
        ),
        secret_store=LocalSecretStore(root=root),
        transport=app_transport,
    )


def _allow_github_egress(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str = "full-trusted-local",
    allowlist: tuple[str, ...] = (),
) -> None:
    monkeypatch.setenv("ZEBRA_SCM_NETWORK_PROFILE", profile)
    monkeypatch.setenv("ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST", ",".join(allowlist))


class _FakeGitHubTransport:
    def __init__(self, *, url: str) -> None:
        self._url = url
        self.payload: GitHubPullRequestPayload | None = None
        self.token: str | None = None

    def create_pull_request(
        self,
        payload: GitHubPullRequestPayload,
        *,
        token: str,
    ) -> str:
        self.payload = payload
        self.token = token
        return self._url


class _FakeScmProxyTransport:
    def __init__(self, *, url: str) -> None:
        self._url = url
        self.last_request: ScmProxyRequest | None = None

    def execute(self, request: ScmProxyRequest) -> ScmProxyResponse:
        self.last_request = request
        return ScmProxyResponse(
            status_code=201,
            body={"html_url": self._url},
            metadata={"transport": "proxy"},
        )


class _FailingScmProxyTransport:
    def execute(self, request: ScmProxyRequest) -> ScmProxyResponse:
        raise ScmUnavailableError(
            "scm proxy execution failed: proxy offline",
            metadata={"failure_class": "transport_failure"},
        )


class _FailingGitHubTransport:
    def create_pull_request(
        self,
        payload: GitHubPullRequestPayload,
        *,
        token: str,
    ) -> str:
        raise ScmUnavailableError(
            "github pull request execution failed: transport offline",
            metadata={"failure_class": "transport_failure"},
        )


class _FakeGitHubAppTransport:
    def create_installation_token(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: str,
        now: datetime,
    ) -> GitHubAppInstallationToken:
        assert app_id == "app-123"
        assert installation_id == "inst-123"
        assert private_key == "private-key-material"
        return GitHubAppInstallationToken(
            token_value="github-app-token",
            expires_at=datetime(2026, 7, 23, 12, 30, tzinfo=UTC),
        )


class _FailingGitHubAppTransport:
    def create_installation_token(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: str,
        now: datetime,
    ) -> GitHubAppInstallationToken:
        raise RuntimeError("token exchange offline")
