from pathlib import Path
from subprocess import run

import pytest
from agent_integrations import (
    GitHubPullRequestConfig,
    GitHubPullRequestGateway,
    LocalOnlyPullRequestGateway,
    PullRequestRequest,
    ScmUnavailableError,
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
        GitHubPullRequestConfig(owner="octo-org", repo="zebra-agent")
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
        GitHubPullRequestConfig(owner="octo-org", repo="zebra-agent")
    )

    with pytest.raises(ScmUnavailableError, match="github token is required"):
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
