from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run
from typing import Protocol
from urllib.parse import urlparse

from agent_security import (
    DEFAULT_NETWORK_PROFILE,
    CredentialBroker,
    NetworkProfile,
    NetworkProfileName,
    ScmCredentialCapability,
    parse_network_profile,
)

from agent_integrations.provider_settings import ScmProviderSettings
from agent_integrations.scm_credentials import CredentialLookupResult, github_token_from_broker
from agent_integrations.scm_errors import ScmIntegrationError, ScmUnavailableError
from agent_integrations.scm_proxy import (
    JsonValue,
    ScmProxyTransport,
    build_github_pull_request_proxy_request,
)
from agent_integrations.scm_proxy_http import ScmHttpProxyTransport


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
    route: str | None = None
    proxy_target: str | None = None
    proxy_transport: str | None = None


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


class GitHubProxyPullRequestTransport:
    def __init__(self, *, proxy_transport: ScmProxyTransport) -> None:
        self._proxy_transport = proxy_transport

    def create_pull_request(
        self,
        payload: GitHubPullRequestPayload,
        *,
        token: str,
    ) -> str:
        request = build_github_pull_request_proxy_request(
            endpoint=payload.endpoint,
            headers=payload.headers,
            body=_json_proxy_body(payload.body),
            token=token,
            credential_source=None,
            credential_backend=None,
        )
        response = self._proxy_transport.execute(request)
        url = response.body.get("html_url")
        if not isinstance(url, str) or not url.strip():
            raise ScmUnavailableError(
                "github proxy pull request response did not include html_url",
                metadata={"failure_class": "transport_failure"},
            )
        return url

    @property
    def audit_metadata(self) -> dict[str, str]:
        return {
            "route": "proxy",
            "proxy_target": "github.pull_request.create",
            "proxy_transport": "scm_http_proxy",
        }


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
        network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE,
        transport: GitHubPullRequestTransport | None = None,
    ) -> None:
        self._config = config
        self._credential_broker = credential_broker
        self._credential_now = credential_now
        self._credential_source_fallback = credential_source_fallback
        self._credential_backend_fallback = credential_backend_fallback
        self._network_profile = network_profile
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
                route=_transport_route(self._transport),
                proxy_target=_transport_proxy_target(self._transport),
                proxy_transport=_transport_proxy_transport(self._transport),
            )
        if not self._config.execution_enabled:
            raise ScmUnavailableError(
                "github pull request execution requires ZEBRA_SCM_PULL_REQUEST_DRY_RUN=false"
            )
        _ensure_github_egress_allowed(
            network_profile=self._network_profile,
            api_base_url=self._config.api_base_url,
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
            route=_transport_route(self._transport),
            proxy_target=_transport_proxy_target(self._transport),
            proxy_transport=_transport_proxy_transport(self._transport),
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
    settings: ScmProviderSettings,
    *,
    env: Mapping[str, str] | None = None,
    credential_broker: CredentialBroker | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
    now: datetime | None = None,
    allow_env_token_fallback: bool = False,
) -> PullRequestGateway:
    active_env = env or os.environ
    if settings.provider == "local-only":
        return LocalOnlyPullRequestGateway()
    if settings.provider == "github":
        if settings.github_owner is None or settings.github_repo is None:
            raise ScmUnavailableError("github owner and repo are required")
        network_profile = _network_profile_from_env(active_env)
        transport = github_transport or _build_github_transport_from_env(active_env)
        token_value = None
        credential_source_fallback = None
        credential_backend_fallback = None
        if not settings.pull_request_dry_run:
            if credential_broker is None:
                if allow_env_token_fallback:
                    capability = ScmCredentialCapability(
                        provider=settings.provider,
                        token_env=settings.github_token_env,
                        token_value=active_env.get(settings.github_token_env or ""),
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
            network_profile=network_profile,
            transport=transport,
        )
    raise ScmUnavailableError(f"unsupported SCM provider: {settings.provider}")


def _network_profile_from_env(env: Mapping[str, str]) -> NetworkProfile:
    raw_profile = env.get("ZEBRA_SCM_NETWORK_PROFILE", DEFAULT_NETWORK_PROFILE.name.value)
    raw_allowlist = env.get("ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST", "")
    domain_allowlist = tuple(
        entry.strip() for entry in raw_allowlist.split(",") if entry.strip()
    )
    return parse_network_profile(
        raw_profile,
        domain_allowlist=domain_allowlist or None,
    )


def _ensure_github_egress_allowed(
    *,
    network_profile: NetworkProfile,
    api_base_url: str,
) -> None:
    target_host = _target_host(api_base_url)
    if network_profile.name is NetworkProfileName.FULL_TRUSTED_LOCAL:
        return
    if (
        network_profile.name is NetworkProfileName.DOMAIN_ALLOWLIST
        and target_host in network_profile.domain_allowlist
    ):
        return
    raise ScmUnavailableError(
        (
            "github pull request execution is blocked by network profile "
            f"{network_profile.name.value}"
        ),
        metadata={
            "failure_class": "egress_policy",
            "network_profile": network_profile.name.value,
            "target_host": target_host,
        },
    )


def _target_host(api_base_url: str) -> str:
    host = urlparse(api_base_url).hostname
    if host is None or not host.strip():
        raise ScmIntegrationError("github api_base_url must include a hostname")
    return host.strip().lower()


def _build_github_transport_from_env(env: Mapping[str, str]) -> GitHubPullRequestTransport | None:
    transport_mode = env.get("ZEBRA_SCM_GITHUB_TRANSPORT", "direct").strip().lower()
    if not transport_mode or transport_mode == "direct":
        return None
    if transport_mode != "proxy":
        raise ScmUnavailableError(
            f"unsupported github transport mode: {transport_mode}"
        )
    proxy_endpoint = env.get("ZEBRA_SCM_PROXY_ENDPOINT", "").strip()
    if not proxy_endpoint:
        raise ScmUnavailableError(
            "ZEBRA_SCM_PROXY_ENDPOINT is required when ZEBRA_SCM_GITHUB_TRANSPORT=proxy"
        )
    return GitHubProxyPullRequestTransport(
        proxy_transport=ScmHttpProxyTransport(proxy_endpoint=proxy_endpoint)
    )


def _json_proxy_body(value: dict[str, object]) -> dict[str, JsonValue]:
    normalized: dict[str, JsonValue] = {}
    for key, item in value.items():
        if isinstance(item, str | int | float | bool) or item is None:
            normalized[key] = item
            continue
        raise ScmIntegrationError("github pull request payload must be JSON-serializable")
    return normalized


def _transport_route(transport: GitHubPullRequestTransport) -> str:
    if isinstance(transport, GitHubProxyPullRequestTransport):
        return "proxy"
    return "direct"


def _transport_proxy_target(transport: GitHubPullRequestTransport) -> str | None:
    if isinstance(transport, GitHubProxyPullRequestTransport):
        return transport.audit_metadata["proxy_target"]
    return None


def _transport_proxy_transport(transport: GitHubPullRequestTransport) -> str | None:
    if isinstance(transport, GitHubProxyPullRequestTransport):
        return transport.audit_metadata["proxy_transport"]
    return None


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
