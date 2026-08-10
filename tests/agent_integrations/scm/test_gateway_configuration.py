from pathlib import Path

import pytest
from agent_integrations import (
    GitHubPullRequestGateway,
    LocalOnlyPullRequestGateway,
    PullRequestRequest,
    ScmProviderSettings,
    ScmUnavailableError,
    build_pull_request_gateway,
)
from agent_security import (
    InMemoryCredentialBroker,
)
from scm_support import (
    _assert_secret_absent,
    _FailingGitHubAppTransport,
    _FailingGitHubTransport,
    _FakeGitHubTransport,
    _git_workspace,
    _github_app_broker,
    _github_capability,
    _github_scm,
    _network_env,
    _now,
)


def test_build_pull_request_gateway_defaults_to_local_only() -> None:
    gateway = build_pull_request_gateway(
        ScmProviderSettings(
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
        ScmProviderSettings(
            provider="github",
            github_owner="octo-org",
            github_repo="zebra-agent",
            github_token_env="GITHUB_TOKEN",
            github_api_base_url="https://api.github.com",
            pull_request_dry_run=True,
        )
    )

    assert isinstance(gateway, GitHubPullRequestGateway)

def test_build_pull_request_gateway_does_not_use_env_token_fallback_by_default(
    tmp_path: Path,
) -> None:
    gateway = build_pull_request_gateway(
        ScmProviderSettings(
            provider="github",
            github_owner="octo-org",
            github_repo="zebra-agent",
            github_token_env="GITHUB_TOKEN",
            github_api_base_url="https://api.github.com",
            pull_request_dry_run=False,
        ),
        env={
            "GITHUB_TOKEN": "secret-token",
            **_network_env(profile="full-trusted-local"),
        },
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
    )

    assert isinstance(gateway, GitHubPullRequestGateway)
    with pytest.raises(ScmUnavailableError, match="github token is required"):
        gateway.plan(
            _git_workspace(tmp_path / "workspace"),
            PullRequestRequest(
                title="Add feature",
                body="Implementation details.",
                base_branch="main",
                head_branch="feature/zebra",
                dry_run=False,
            ),
        )

def test_build_pull_request_gateway_uses_explicit_env_token_fallback(
    tmp_path: Path,
) -> None:
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env={
            "GITHUB_TOKEN": "secret-token",
            **_network_env(profile="full-trusted-local"),
        },
        github_transport=transport,
        allow_env_token_fallback=True,
    )

    plan = gateway.plan(
        _git_workspace(tmp_path / "workspace"),
        PullRequestRequest(
            title="Add feature",
            body="Implementation details.",
            base_branch="main",
            head_branch="feature/zebra",
            dry_run=False,
        ),
    )

    assert plan.status == "created"
    assert transport.token == "secret-token"
    assert plan.credential_source == "env_fallback"
    assert plan.credential_backend == "environment"

def test_build_pull_request_gateway_dry_run_does_not_request_broker_credential(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=True),
        credential_broker=InMemoryCredentialBroker(unavailable=True),
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
    assert plan.request_payload is not None
    headers = plan.request_payload["headers"]
    assert isinstance(headers, dict)
    assert "Authorization" not in headers

def test_build_pull_request_gateway_uses_broker_credential_for_execution(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
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

    assert plan.provider == "github"
    assert plan.status == "created"
    assert plan.url == "https://github.example/pulls/1"
    assert plan.credential_source == "broker"
    assert plan.credential_backend == "environment"
    assert transport.token == "broker-token"
    _assert_secret_absent("broker-token", plan)

def test_build_pull_request_gateway_uses_github_app_broker_for_execution(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        credential_broker=_github_app_broker(tmp_path),
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
    assert plan.credential_source == "broker"
    assert plan.credential_backend == "github_app"
    assert transport.token == "github-app-token"

def test_build_pull_request_gateway_fails_before_execution_when_broker_credential_missing(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        credential_broker=InMemoryCredentialBroker(),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
        now=_now(),
    )

    with pytest.raises(ScmUnavailableError, match="missing") as excinfo:
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
        "credential_source": "broker",
        "credential_backend": "environment",
        "failure_class": "credential_missing",
    }

def test_build_pull_request_gateway_classifies_github_app_missing_secret(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        credential_broker=_github_app_broker(tmp_path, create_secret=False),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
        now=_now(),
    )

    with pytest.raises(ScmUnavailableError, match="private key is missing") as excinfo:
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
        "credential_source": "broker",
        "credential_backend": "github_app",
        "failure_class": "credential_missing",
    }

def test_build_pull_request_gateway_classifies_broker_denied_credential(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        credential_broker=InMemoryCredentialBroker(
            capabilities=(_github_capability(),),
            denied_audiences=frozenset({"repo:octo-org/zebra-agent"}),
        ),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
        now=_now(),
    )

    with pytest.raises(ScmUnavailableError, match="denied") as excinfo:
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
        "credential_source": "broker",
        "credential_backend": "environment",
        "failure_class": "credential_denied",
    }

def test_build_pull_request_gateway_classifies_broker_unavailable(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        credential_broker=InMemoryCredentialBroker(unavailable=True),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
        now=_now(),
    )

    with pytest.raises(ScmUnavailableError, match="unavailable") as excinfo:
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
        "credential_source": "broker",
        "credential_backend": "environment",
        "failure_class": "credential_unavailable",
    }

def test_build_pull_request_gateway_records_explicit_env_fallback_missing_metadata(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
        allow_env_token_fallback=True,
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
    assert excinfo.value.metadata == {
        "credential_source": "env_fallback",
        "credential_backend": "environment",
        "failure_class": "credential_missing",
    }

def test_build_pull_request_gateway_classifies_github_app_transport_failure(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        credential_broker=_github_app_broker(
            tmp_path,
            app_transport=_FailingGitHubAppTransport(),
        ),
        github_transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
        now=_now(),
    )

    with pytest.raises(ScmUnavailableError, match="token exchange failed") as excinfo:
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
        "credential_source": "broker",
        "credential_backend": "github_app",
        "failure_class": "transport_failure",
    }

def test_build_pull_request_gateway_classifies_transport_failure(
    tmp_path: Path,
) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    gateway = build_pull_request_gateway(
        _github_scm(pull_request_dry_run=False),
        env=_network_env(profile="full-trusted-local"),
        credential_broker=InMemoryCredentialBroker.with_capabilities([_github_capability()]),
        github_transport=_FailingGitHubTransport(),
        now=_now(),
    )

    with pytest.raises(ScmUnavailableError, match="transport offline") as excinfo:
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
        "credential_source": "broker",
        "credential_backend": "environment",
        "failure_class": "transport_failure",
    }
