from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import run
from typing import Protocol

from zebra_agent_config import ScmSettings


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
    request_payload: dict[str, object] | None = None


class PullRequestGateway(Protocol):
    def plan(self, workspace_root: Path, request: PullRequestRequest) -> PullRequestPlan:
        raise NotImplementedError


@dataclass(frozen=True)
class GitHubPullRequestConfig:
    owner: str
    repo: str
    token: str | None = None
    api_base_url: str = "https://api.github.com"

    def __post_init__(self) -> None:
        if not self.owner.strip():
            raise ValueError("github owner must not be blank")
        if not self.repo.strip():
            raise ValueError("github repo must not be blank")
        if not self.api_base_url.strip():
            raise ValueError("github api_base_url must not be blank")
        if self.token is not None and not self.token.strip():
            raise ValueError("github token must not be blank when provided")


@dataclass(frozen=True)
class GitHubPullRequestPayload:
    endpoint: str
    headers: dict[str, str]
    body: dict[str, object]


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


class GitHubPullRequestGateway:
    def __init__(self, config: GitHubPullRequestConfig) -> None:
        self._config = config

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
        payload = self.build_payload(
            PullRequestRequest(
                title=request.title,
                body=request.body,
                base_branch=request.base_branch,
                head_branch=head_branch,
                dry_run=request.dry_run,
            )
        )
        if request.dry_run:
            return PullRequestPlan(
                provider="github",
                title=request.title.strip(),
                body=request.body.strip(),
                base_branch=request.base_branch.strip(),
                head_branch=head_branch,
                commit_sha=commit_sha,
                dry_run=True,
                status="dry_run",
                request_payload=_serializable_payload(payload),
            )
        if self._config.token is None:
            raise ScmUnavailableError("github token is required for pull request execution")
        raise ScmUnavailableError("github pull request execution is not implemented")

    def build_payload(self, request: PullRequestRequest) -> GitHubPullRequestPayload:
        head_branch = request.head_branch
        if head_branch is None:
            raise ScmIntegrationError("github pull request requires head_branch")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._config.token is not None:
            headers["Authorization"] = "Bearer <redacted>"
        return GitHubPullRequestPayload(
            endpoint=(
                f"{self._config.api_base_url.rstrip('/')}/repos/"
                f"{self._config.owner.strip()}/{self._config.repo.strip()}/pulls"
            ),
            headers=headers,
            body={
                "title": request.title.strip(),
                "body": request.body.strip(),
                "base": request.base_branch.strip(),
                "head": head_branch.strip(),
                "maintainer_can_modify": True,
                "draft": False,
            },
        )


def build_pull_request_gateway(settings: ScmSettings) -> PullRequestGateway:
    if settings.provider == "local-only":
        return LocalOnlyPullRequestGateway()
    if settings.provider == "github":
        if settings.github_owner is None or settings.github_repo is None:
            raise ScmUnavailableError("github owner and repo are required")
        return GitHubPullRequestGateway(
            GitHubPullRequestConfig(
                owner=settings.github_owner,
                repo=settings.github_repo,
                token=None,
                api_base_url=settings.github_api_base_url,
            )
        )
    raise ScmUnavailableError(f"unsupported SCM provider: {settings.provider}")


def _serializable_payload(payload: GitHubPullRequestPayload) -> dict[str, object]:
    return {
        "endpoint": payload.endpoint,
        "headers": dict(payload.headers),
        "body": _json_object(payload.body),
    }


def _json_object(value: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, str | int | float | bool) or item is None:
            normalized[key] = item
        else:
            normalized[key] = str(item)
    return normalized


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
