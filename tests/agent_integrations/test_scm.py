import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run

import pytest
from agent_integrations import (
    GitHubAppCredentialBinding,
    GitHubAppCredentialBroker,
    GitHubAppInstallationToken,
    GitHubAppTokenTransport,
    GitHubPullRequestConfig,
    GitHubPullRequestGateway,
    GitHubPullRequestPayload,
    LocalOnlyPullRequestGateway,
    PullRequestRequest,
    ScmUnavailableError,
    build_pull_request_gateway,
)
from agent_security import CredentialCapability, InMemoryCredentialBroker, LocalSecretStore
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


def test_build_pull_request_gateway_does_not_use_env_token_fallback_by_default(
    tmp_path: Path,
) -> None:
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
        env={"GITHUB_TOKEN": "secret-token"},
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
        env={},
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


def _github_scm(*, pull_request_dry_run: bool) -> ScmSettings:
    return ScmSettings(
        provider="github",
        github_owner="octo-org",
        github_repo="zebra-agent",
        github_token_env="GITHUB_TOKEN",
        github_api_base_url="https://api.github.com",
        pull_request_dry_run=pull_request_dry_run,
    )


def _github_capability() -> CredentialCapability:
    return CredentialCapability(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create",),
        expires_at=datetime(2026, 6, 23, 12, 30, tzinfo=UTC),
        token_value="broker-token",
    )


def _now() -> datetime:
    return datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def _github_app_broker(
    tmp_path: Path,
    *,
    create_secret: bool = True,
    app_transport: GitHubAppTokenTransport | None = None,
) -> GitHubAppCredentialBroker:
    root = tmp_path / "github-app-secrets"
    secret_path = root / "github" / "app"
    secret_path.mkdir(parents=True, exist_ok=True)
    if create_secret:
        (secret_path / "private-key.json").write_text(
            json.dumps({"value": "private-key-material", "version": "v1"}),
            encoding="utf-8",
        )
    if app_transport is None:
        app_transport = _FakeGitHubAppTransport()
    return GitHubAppCredentialBroker(
        bindings=(
            GitHubAppCredentialBinding(
                audience="repo:octo-org/zebra-agent",
                installation_id="inst-123",
                app_id="app-123",
                private_key_handle="github/app/private-key",
                scopes=("pull_request:create",),
            ),
        ),
        secret_store=LocalSecretStore(root=root),
        transport=app_transport,
    )


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


class _FakeGitHubAppTransport:
    def create_installation_token(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: str,
        now: datetime,
    ) -> GitHubAppInstallationToken:
        assert app_id == "app-123"
        assert installation_id == "inst-123"
        assert private_key == "private-key-material"
        return GitHubAppInstallationToken(
            token_value="github-app-token",
            expires_at=datetime(2026, 6, 23, 12, 30, tzinfo=UTC),
        )


class _FailingGitHubAppTransport:
    def create_installation_token(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: str,
        now: datetime,
    ) -> GitHubAppInstallationToken:
        raise RuntimeError("token exchange offline")


class _FailingGitHubTransport:
    def create_pull_request(
        self,
        payload: GitHubPullRequestPayload,
        *,
        token: str,
    ) -> str:
        raise ScmUnavailableError(
            "github pull request execution failed: transport offline",
            metadata={"failure_class": "transport_failure"},
        )


def _assert_secret_absent(secret: str, value: object) -> None:
    assert secret not in repr(value)
