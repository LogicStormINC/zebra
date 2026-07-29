import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_integrations import (
    GitHubAppCredentialBinding,
    GitHubAppCredentialBroker,
    GitHubAppInstallationToken,
    GitHubAppTokenTransport,
    GitHubPullRequestPayload,
    ScmProxyRequest,
    ScmProxyResponse,
    ScmUnavailableError,
)
from agent_security import (
    CredentialBroker,
    CredentialCapability,
    EnvironmentCredentialBinding,
    EnvironmentCredentialBroker,
    InMemoryCredentialBroker,
    LocalSecretStore,
)
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_config import ApiSettings, ModelSettings, ScmSettings, ZebraAgentSettings

_VALID_CREDENTIAL_EXPIRY = datetime.max.replace(tzinfo=UTC)


def _seed_ready_session(
    database_path: Path,
    workspace_root: Path,
    *,
    policy_profile: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Pull request session",
            user_input="Open a pull request.",
            workspace_root=workspace_root.resolve(),
            policy_profile=policy_profile,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id

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

def _settings(auth_token: str | None, *, scm: ScmSettings | None = None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        scm=scm or _local_scm(),
    )

def _local_scm() -> ScmSettings:
    return ScmSettings(
        provider="local-only",
        github_owner=None,
        github_repo=None,
        github_token_env=None,
        github_api_base_url="https://api.github.com",
        pull_request_dry_run=True,
    )

def _github_scm(*, pull_request_dry_run: bool = True) -> ScmSettings:
    return ScmSettings(
        provider="github",
        github_owner="octo-org",
        github_repo="zebra-agent",
        github_token_env="ZEBRA_TEST_MISSING_GITHUB_TOKEN",
        github_api_base_url="https://api.github.com",
        pull_request_dry_run=pull_request_dry_run,
    )

def _github_broker(*, env: dict[str, str]) -> EnvironmentCredentialBroker:
    return EnvironmentCredentialBroker(
        bindings=(
            EnvironmentCredentialBinding(
                provider="github",
                audience="repo:octo-org/zebra-agent",
                scopes=("pull_request:create",),
                token_env="GITHUB_TOKEN",
                expires_at=_VALID_CREDENTIAL_EXPIRY,
            ),
        ),
        env=env,
    )

def _denied_github_broker() -> CredentialBroker:
    return InMemoryCredentialBroker(
        capabilities=(_github_capability(),),
        denied_audiences=frozenset({"repo:octo-org/zebra-agent"}),
    )

def _unavailable_github_broker() -> InMemoryCredentialBroker:
    return InMemoryCredentialBroker(unavailable=True)

def _github_capability() -> CredentialCapability:
    return CredentialCapability(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create",),
        expires_at=_VALID_CREDENTIAL_EXPIRY,
        token_value="broker-token",
    )

def _github_app_broker(
    tmp_path: Path,
    *,
    app_transport: GitHubAppTokenTransport | None = None,
) -> GitHubAppCredentialBroker:
    root = tmp_path / "github-app-secrets"
    secret_path = root / "github" / "app"
    secret_path.mkdir(parents=True, exist_ok=True)
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

def _allow_github_egress(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str = "full-trusted-local",
    allowlist: tuple[str, ...] = (),
) -> None:
    monkeypatch.setenv("ZEBRA_SCM_NETWORK_PROFILE", profile)
    monkeypatch.setenv("ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST", ",".join(allowlist))

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

class _FakeScmProxyTransport:
    def __init__(self, *, url: str) -> None:
        self._url = url
        self.last_request: ScmProxyRequest | None = None

    def execute(self, request: ScmProxyRequest) -> ScmProxyResponse:
        self.last_request = request
        return ScmProxyResponse(
            status_code=201,
            body={"html_url": self._url},
            metadata={"transport": "proxy"},
        )

class _FailingScmProxyTransport:
    def execute(self, request: ScmProxyRequest) -> ScmProxyResponse:
        raise ScmUnavailableError(
            "scm proxy execution failed: proxy offline",
            metadata={"failure_class": "transport_failure"},
        )

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
            expires_at=_VALID_CREDENTIAL_EXPIRY,
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
