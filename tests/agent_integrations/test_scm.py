from pathlib import Path
from subprocess import run

import pytest
from agent_integrations import (
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
