from pathlib import Path
from subprocess import run

import pytest
from agent_integrations import (
    GitHubPullRequestConfig,
    GitHubPullRequestGateway,
    GitHubPullRequestPayload,
    LocalOnlyPullRequestGateway,
    PullRequestRequest,
    ScmUnavailableError,
    build_pull_request_gateway,
)
from zebra_agent_config import ScmSettings


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
        )
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


def test_build_pull_request_gateway_defaults_to_local_only() -> None:
    gateway = build_pull_request_gateway(
        ScmSettings(
            provider="local-only",
            github_owner=None,
            github_repo=None,
            github_token_env=None,
            github_api_base_url="https://api.github.com",
            pull_request_dry_run=True,
        )
    )

    assert isinstance(gateway, LocalOnlyPullRequestGateway)


def test_build_pull_request_gateway_selects_github() -> None:
    gateway = build_pull_request_gateway(
        ScmSettings(
            provider="github",
            github_owner="octo-org",
            github_repo="zebra-agent",
            github_token_env="GITHUB_TOKEN",
            github_api_base_url="https://api.github.com",
            pull_request_dry_run=True,
        )
    )

    assert isinstance(gateway, GitHubPullRequestGateway)


def test_build_pull_request_gateway_reads_token_only_when_execution_enabled() -> None:
    gateway = build_pull_request_gateway(
        ScmSettings(
            provider="github",
            github_owner="octo-org",
            github_repo="zebra-agent",
            github_token_env="GITHUB_TOKEN",
            github_api_base_url="https://api.github.com",
            pull_request_dry_run=False,
        ),
        env={"GITHUB_TOKEN": "secret-token"},
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
    )

    assert isinstance(gateway, GitHubPullRequestGateway)


def test_build_pull_request_gateway_rejects_unknown_provider() -> None:
    with pytest.raises(ScmUnavailableError, match="unsupported SCM provider"):
        build_pull_request_gateway(
            ScmSettings(
                provider="unknown",
                github_owner=None,
                github_repo=None,
                github_token_env=None,
                github_api_base_url="https://api.github.com",
                pull_request_dry_run=True,
            )
        )


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
