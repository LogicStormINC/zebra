from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run
from typing import Protocol

from agent_security import CredentialBroker, ScmCredentialBoundary
from zebra_agent_config import ScmSettings

from agent_integrations.scm_credentials import CredentialLookupResult, github_token_from_broker
from agent_integrations.scm_errors import ScmIntegrationError, ScmUnavailableError


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
    credential_source: str | None = None
    credential_backend: str | None = None


class PullRequestGateway(Protocol):
    def plan(self, workspace_root: Path, request: PullRequestRequest) -> PullRequestPlan:
        raise NotImplementedError


class GitHubPullRequestTransport(Protocol):
    def create_pull_request(
        self,
        payload: GitHubPullRequestPayload,
        *,
        token: str,
    ) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class GitHubPullRequestConfig:
    owner: str
    repo: str
    token: str | None = None
    api_base_url: str = "https://api.github.com"
    execution_enabled: bool = False

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
    def __init__(
        self,
        config: GitHubPullRequestConfig,
        *,
        credential_broker: CredentialBroker | None = None,
        credential_now: datetime | None = None,
        credential_source_fallback: str | None = None,
        credential_backend_fallback: str | None = None,
        transport: GitHubPullRequestTransport | None = None,
    ) -> None:
        self._config = config
        self._credential_broker = credential_broker
        self._credential_now = credential_now
        self._credential_source_fallback = credential_source_fallback
        self._credential_backend_fallback = credential_backend_fallback
        if transport is None:
            from agent_integrations.github import GitHubHttpPullRequestTransport

            transport = GitHubHttpPullRequestTransport()
        self._transport = transport

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
        if not self._config.execution_enabled:
            raise ScmUnavailableError(
                "github pull request execution requires ZEBRA_SCM_PULL_REQUEST_DRY_RUN=false"
            )
        token = self._config.token
        lookup: CredentialLookupResult | None = None
        if token is None and self._credential_broker is not None:
            lookup = github_token_from_broker(
                owner=self._config.owner,
                repo=self._config.repo,
                credential_broker=self._credential_broker,
                now=self._credential_now or datetime.now(UTC),
            )
            token = lookup.token_value
        if token is None:
            metadata: dict[str, object] | None = None
            if self._credential_source_fallback is not None:
                metadata = {
                    "credential_source": self._credential_source_fallback,
                    "credential_backend": self._credential_backend_fallback,
                    "failure_class": "credential_missing",
                }
            raise ScmUnavailableError(
                "github token is required for pull request execution",
                metadata=metadata,
            )
        credential_source = lookup.credential_source if lookup is not None else "env_fallback"
        credential_backend = lookup.credential_backend if lookup is not None else "environment"
        try:
            url = self._transport.create_pull_request(payload, token=token)
        except ScmUnavailableError as error:
            metadata = dict(error.metadata)
            metadata.setdefault("credential_source", credential_source)
            metadata.setdefault("credential_backend", credential_backend)
            raise ScmUnavailableError(str(error), metadata=metadata) from error
        return PullRequestPlan(
            provider="github",
            title=request.title.strip(),
            body=request.body.strip(),
            base_branch=request.base_branch.strip(),
            head_branch=head_branch,
            commit_sha=commit_sha,
            dry_run=False,
            status="created",
            url=url,
            request_payload=_serializable_payload(payload),
            credential_source=credential_source,
            credential_backend=credential_backend,
        )

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


def build_pull_request_gateway(
    settings: ScmSettings,
    *,
    env: Mapping[str, str] | None = None,
    credential_broker: CredentialBroker | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
    now: datetime | None = None,
    allow_env_token_fallback: bool = False,
) -> PullRequestGateway:
    if settings.provider == "local-only":
        return LocalOnlyPullRequestGateway()
    if settings.provider == "github":
        if settings.github_owner is None or settings.github_repo is None:
            raise ScmUnavailableError("github owner and repo are required")
        token_value = None
        credential_source_fallback = None
        credential_backend_fallback = None
        if not settings.pull_request_dry_run:
            if credential_broker is None:
                if allow_env_token_fallback:
                    values = env or os.environ
                    capability = ScmCredentialBoundary().capability_from_settings(
                        settings,
                        token_value=values.get(settings.github_token_env or ""),
                    )
                    token_value = capability.token_value
                    credential_source_fallback = "env_fallback"
                    credential_backend_fallback = "environment"
        return GitHubPullRequestGateway(
            GitHubPullRequestConfig(
                owner=settings.github_owner,
                repo=settings.github_repo,
                token=token_value,
                api_base_url=settings.github_api_base_url,
                execution_enabled=not settings.pull_request_dry_run,
            ),
            credential_broker=credential_broker,
            credential_now=now,
            credential_source_fallback=credential_source_fallback,
            credential_backend_fallback=credential_backend_fallback,
            transport=github_transport,
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
