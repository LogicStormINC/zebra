from pathlib import Path

import pytest
from agent_integrations import (
    GitHubProxyPullRequestTransport,
    PullRequestRequest,
    ScmUnavailableError,
    build_pull_request_gateway,
)
from agent_security import (
    InMemoryCredentialBroker,
)
from scm_support import (
    _FakeGitHubTransport,
    _FakeScmProxyTransport,
    _git_workspace,
    _github_capability,
    _github_scm,
    _network_env,
    _now,
)
from zebra_agent_config import ScmSettings


def test_build_pull_request_gateway_blocks_remote_execution_by_default_network_profile(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        credential_broker=InMemoryCredentialBroker.with_capabilities([_github_capability()]),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
        now=_now(),
    )

    with pytest.raises(ScmUnavailableError, match="blocked by network profile none") as excinfo:
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
    assert excinfo.value.metadata == {
        "failure_class": "egress_policy",
        "network_profile": "none",
        "target_host": "api.github.com",
    }

def test_build_pull_request_gateway_allows_domain_allowlist_profile(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="domain-allowlist", allowlist=("api.github.com",)),
        credential_broker=InMemoryCredentialBroker.with_capabilities([_github_capability()]),
        github_transport=transport,
        now=_now(),
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

    assert plan.status == "created"
    assert transport.token == "broker-token"

def test_build_pull_request_gateway_uses_proxy_transport_when_configured(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    proxy_transport = _FakeScmProxyTransport(url="https://github.example/pulls/2")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env={
            **_network_env(profile="full-trusted-local"),
            "ZEBRA_SCM_GITHUB_TRANSPORT": "proxy",
            "ZEBRA_SCM_PROXY_ENDPOINT": "https://proxy.example/scm",
        },
        credential_broker=InMemoryCredentialBroker.with_capabilities([_github_capability()]),
        github_transport=GitHubProxyPullRequestTransport(proxy_transport=proxy_transport),
        now=_now(),
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

    assert plan.status == "created"
    assert plan.url == "https://github.example/pulls/2"
    assert proxy_transport.last_request is not None
    assert proxy_transport.last_request.provider == "github"
    assert proxy_transport.last_request.action == "pull_request.create"
    assert proxy_transport.last_request.secret_headers == (
        ("Authorization", "Bearer broker-token"),
    )
    assert "broker-token" not in repr(proxy_transport.last_request.to_serializable())

def test_build_pull_request_gateway_rejects_proxy_mode_without_endpoint() -> None:
    with pytest.raises(ScmUnavailableError, match="ZEBRA_SCM_PROXY_ENDPOINT is required"):
        build_pull_request_gateway(
            _github_scm(pull_request_dry_run=False),
            env={
                **_network_env(profile="full-trusted-local"),
                "ZEBRA_SCM_GITHUB_TRANSPORT": "proxy",
            },
        )

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
