import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run

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
    CredentialCapability,
    LocalSecretStore,
)
from zebra_agent_config import ScmSettings


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

def _network_env(
    *,
    profile: str,
    allowlist: tuple[str, ...] = (),
) -> dict[str, str]:
    return {
        "ZEBRA_SCM_NETWORK_PROFILE": profile,
        "ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST": ",".join(allowlist),
    }

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
