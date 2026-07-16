from pathlib import Path

import pytest
from agent_integrations import (
    GitHubPullRequestConfig,
    GitHubPullRequestGateway,
    LocalOnlyPullRequestGateway,
    PullRequestRequest,
    ScmUnavailableError,
)
from agent_security import (
    parse_network_profile,
)
from scm_support import (
    _assert_secret_absent,
    _FakeGitHubTransport,
    _git_workspace,
)


def test_local_only_pull_request_gateway_builds_dry_run_plan(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")

    plan = LocalOnlyPullRequestGateway().plan(
        workspace,
        PullRequestRequest(
            title="Add feature",
            body="Implementation details.",
            base_branch="main",
            dry_run=True,
        ),
    )

    assert plan.provider == "local-only"
    assert plan.title == "Add feature"
    assert plan.body == "Implementation details."
    assert plan.base_branch == "main"
    assert plan.head_branch
    assert len(plan.commit_sha) == 40
    assert plan.dry_run is True
    assert plan.status == "dry_run"
    assert plan.url is None

def test_local_only_pull_request_gateway_rejects_network_execution(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")

    with pytest.raises(ScmUnavailableError, match="local-only mode"):
        LocalOnlyPullRequestGateway().plan(
            workspace,
            PullRequestRequest(
                title="Add feature",
                body="Implementation details.",
                base_branch="main",
                dry_run=False,
            ),
        )

def test_github_pull_request_gateway_builds_dry_run_plan(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = GitHubPullRequestGateway(
        GitHubPullRequestConfig(
            owner="octo-org",
            repo="zebra-agent",
            execution_enabled=True,
        )
    )

    plan = gateway.plan(
        workspace,
        PullRequestRequest(
            title="Add feature",
            body="Implementation details.",
            base_branch="main",
            head_branch="feature/zebra",
            dry_run=True,
        ),
    )

    assert plan.provider == "github"
    assert plan.status == "dry_run"
    assert plan.dry_run is True
    assert plan.head_branch == "feature/zebra"
    assert len(plan.commit_sha) == 40
    assert plan.request_payload == {
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

def test_github_pull_request_gateway_fails_missing_token_before_execution(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = GitHubPullRequestGateway(
        GitHubPullRequestConfig(
            owner="octo-org",
            repo="zebra-agent",
            execution_enabled=True,
        ),
        network_profile=parse_network_profile("full-trusted-local"),
    )

    with pytest.raises(ScmUnavailableError, match="github token is required") as excinfo:
        gateway.plan(
            workspace,
            PullRequestRequest(
                title="Add feature",
                body="Implementation details.",
                base_branch="main",
                head_branch="feature/zebra",
                dry_run=False,
            ),
        )
    assert excinfo.value.metadata == {}

def test_github_pull_request_gateway_requires_execution_enablement(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = GitHubPullRequestGateway(
        GitHubPullRequestConfig(
            owner="octo-org",
            repo="zebra-agent",
            token="secret-token",
        )
    )

    with pytest.raises(ScmUnavailableError, match="ZEBRA_SCM_PULL_REQUEST_DRY_RUN=false"):
        gateway.plan(
            workspace,
            PullRequestRequest(
                title="Add feature",
                body="Implementation details.",
                base_branch="main",
                head_branch="feature/zebra",
                dry_run=False,
            ),
        )

def test_github_pull_request_gateway_executes_with_fake_transport(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")
    gateway = GitHubPullRequestGateway(
        GitHubPullRequestConfig(
            owner="octo-org",
            repo="zebra-agent",
            token="secret-token",
            execution_enabled=True,
        ),
        network_profile=parse_network_profile("full-trusted-local"),
        transport=transport,
    )

    plan = gateway.plan(
        workspace,
        PullRequestRequest(
            title="Add feature",
            body="Implementation details.",
            base_branch="main",
            head_branch="feature/zebra",
            dry_run=False,
        ),
    )

    assert plan.provider == "github"
    assert plan.status == "created"
    assert plan.dry_run is False
    assert plan.url == "https://github.example/pulls/1"
    assert transport.token == "secret-token"
    assert transport.payload is not None
    assert transport.payload.body["title"] == "Add feature"

def test_github_pull_request_gateway_plan_does_not_expose_token(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")
    gateway = GitHubPullRequestGateway(
        GitHubPullRequestConfig(
            owner="octo-org",
            repo="zebra-agent",
            token="secret-token",
            execution_enabled=True,
        ),
        network_profile=parse_network_profile("full-trusted-local"),
        transport=transport,
    )

    plan = gateway.plan(
        workspace,
        PullRequestRequest(
            title="Add feature",
            body="Implementation details.",
            base_branch="main",
            head_branch="feature/zebra",
            dry_run=False,
        ),
    )

    _assert_secret_absent("secret-token", plan)
    assert plan.request_payload is not None
    assert plan.request_payload["headers"] == {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer <redacted>",
    }

def test_github_pull_request_gateway_serializes_request_with_redacted_token() -> None:
    gateway = GitHubPullRequestGateway(
        GitHubPullRequestConfig(
            owner="octo-org",
            repo="zebra-agent",
            token="secret-token",
            api_base_url="https://github.example/api",
        )
    )

    payload = gateway.build_payload(
        PullRequestRequest(
            title=" Add feature ",
            body=" Implementation details. ",
            base_branch=" main ",
            head_branch=" feature/zebra ",
        )
    )

    assert payload.endpoint == "https://github.example/api/repos/octo-org/zebra-agent/pulls"
    assert payload.headers == {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer <redacted>",
    }
    assert payload.body == {
        "title": "Add feature",
        "body": "Implementation details.",
        "base": "main",
        "head": "feature/zebra",
        "maintainer_can_modify": True,
        "draft": False,
    }
