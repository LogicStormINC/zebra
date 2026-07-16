from pathlib import Path

from agent_storage import SQLiteDeliveryAuditStore
from pull_request_support import (
    _git_workspace,
    _github_scm,
    _seed_ready_session,
    _settings,
)
from zebra_agent_api.app import create_app


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
