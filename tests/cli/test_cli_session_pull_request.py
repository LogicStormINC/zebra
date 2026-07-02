from pathlib import Path
from subprocess import run

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_integrations import GitHubPullRequestPayload
from agent_storage import SQLiteDeliveryAuditStore, SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app as build_app
from zebra_agent_cli.cli import execute
from zebra_agent_config import ApiSettings, ModelSettings, ScmSettings, ZebraAgentSettings


def test_cli_pull_request_returns_local_only_dry_run_plan(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    result = execute(
        [
            "pull-request",
            str(session_id),
            "--title",
            "Add feature",
            "--body",
            "Implementation details.",
            "--base-branch",
            "main",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.command == "pull-request"
    assert result.payload["session_id"] == str(session_id)
    assert result.payload["database"] == str(database_path)
    assert result.payload["policy_profile"] == "full_access"
    assert result.payload["idempotency_key"] is None
    pull_request = result.payload["pull_request"]
    assert isinstance(pull_request, dict)
    assert pull_request["provider"] == "local-only"
    assert pull_request["title"] == "Add feature"
    assert pull_request["body"] == "Implementation details."
    assert pull_request["base_branch"] == "main"
    assert pull_request["dry_run"] is True
    assert pull_request["status"] == "dry_run"
    assert pull_request["url"] is None
    assert len(SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)) == 1


def test_cli_pull_request_reports_created_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZEBRA_SCM_NETWORK_PROFILE", "full-trusted-local")
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")

    def _create_app(database: Path, *, settings: ZebraAgentSettings) -> object:
        return build_app(
            database,
            settings=settings,
            credential_env={"ZEBRA_TEST_MISSING_GITHUB_TOKEN": "cli-broker-token"},
            github_transport=transport,
        )

    monkeypatch.setattr(
        "zebra_agent_cli.session_pull_request_write.create_app",
        _create_app,
    )

    result = execute(
        [
            "pull-request",
            str(session_id),
            "--title",
            "Ship feature",
            "--base-branch",
            "main",
            "--head-branch",
            "feature/zebra",
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path, scm=_github_scm(pull_request_dry_run=False)),
    )

    pull_request = result.payload["pull_request"]
    assert isinstance(pull_request, dict)
    assert pull_request["provider"] == "github"
    assert pull_request["status"] == "created"
    assert pull_request["url"] == "https://github.example/pulls/1"
    assert pull_request["credential_source"] == "broker"
    assert pull_request["credential_backend"] == "environment"
    assert result.payload["database"] == str(database_path)
    assert transport.token == "cli-broker-token"


def test_cli_pull_request_rejects_policy_blocked_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="workspace_write")

    result = execute(
        [
            "pull-request",
            str(session_id),
            "--title",
            "Try PR",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload == {
        "session_id": str(session_id),
        "status": "policy_blocked",
        "reason": "pull request requires full_access session policy",
        "idempotency_key": None,
        "database": str(database_path),
    }


def test_cli_pull_request_rejects_unavailable_execution(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    result = execute(
        [
            "pull-request",
            str(session_id),
            "--title",
            "Try execute",
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload == {
        "session_id": str(session_id),
        "status": "pull_request_unavailable",
        "reason": "pull request execution is unavailable in local-only mode",
        "idempotency_key": None,
        "database": str(database_path),
    }


def test_cli_pull_request_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "pull-request",
            "00000000-0000-0000-0000-000000000001",
            "--title",
            "Missing session",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
        "idempotency_key": None,
        "database": str(database_path),
    }


def test_cli_pull_request_replays_idempotent_response(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    argv = [
        "pull-request",
        str(session_id),
        "--title",
        "Plan once",
        "--idempotency-key",
        "pull-request-key-1",
        "--database",
        str(database_path),
    ]

    first_result = execute(argv, settings=_settings(database_path))
    replayed_result = execute(argv, settings=_settings(database_path))

    assert first_result.payload == replayed_result.payload
    assert replayed_result.payload["idempotency_key"] == "pull-request-key-1"
    assert len(SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)) == 1


def test_cli_pull_request_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    _seed_ready_session(database_path, workspace, policy_profile="full_access")

    result = execute(
        [
            "pull-request",
            "00000000-0000-0000-0000-000000000001",
            "--title",
            "   ",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload == {
        "status": "invalid_request",
        "reason": "title must be a non-blank string",
        "database": str(database_path),
    }


def _seed_ready_session(
    database_path: Path,
    workspace_root: Path,
    *,
    policy_profile: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Pull request session",
            user_input="Open reviewed pull request.",
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


def _settings(database_path: Path, *, scm: ScmSettings | None = None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
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
