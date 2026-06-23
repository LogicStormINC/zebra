from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import run


class ScmIntegrationError(ValueError):
    """Raised when SCM data cannot be read."""


class ScmUnavailableError(ValueError):
    """Raised when a networked SCM action is unavailable."""


@dataclass(frozen=True)
class PullRequestRequest:
    title: str
    body: str
    base_branch: str
    head_branch: str | None = None
    dry_run: bool = True

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("pull request title must not be blank")
        if not self.base_branch.strip():
            raise ValueError("pull request base_branch must not be blank")
        if self.head_branch is not None and not self.head_branch.strip():
            raise ValueError("pull request head_branch must not be blank when provided")


@dataclass(frozen=True)
class PullRequestPlan:
    provider: str
    title: str
    body: str
    base_branch: str
    head_branch: str
    commit_sha: str
    dry_run: bool
    status: str
    url: str | None = None


class LocalOnlyPullRequestGateway:
    def plan(self, workspace_root: Path, request: PullRequestRequest) -> PullRequestPlan:
        root = workspace_root.expanduser().resolve()
        if not root.exists():
            raise ScmIntegrationError("workspace_root does not exist")
        if not root.is_dir():
            raise ScmIntegrationError("workspace_root is not a directory")
        commit_sha = _git(root, ("git", "rev-parse", "HEAD")).strip()
        head_branch = (
            request.head_branch or _git(root, ("git", "rev-parse", "--abbrev-ref", "HEAD")).strip()
        )
        if not request.dry_run:
            raise ScmUnavailableError("pull request execution is unavailable in local-only mode")
        return PullRequestPlan(
            provider="local-only",
            title=request.title.strip(),
            body=request.body.strip(),
            base_branch=request.base_branch.strip(),
            head_branch=head_branch,
            commit_sha=commit_sha,
            dry_run=True,
            status="dry_run",
        )


def _git(workspace_root: Path, command: tuple[str, ...]) -> str:
    completed = run(
        command,
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "git command failed"
        raise ScmIntegrationError(detail)
    return completed.stdout
