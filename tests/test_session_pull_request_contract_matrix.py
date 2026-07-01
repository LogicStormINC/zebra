from pathlib import Path
from subprocess import run

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_integrations import GitHubPullRequestPayload
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app as build_app
from zebra_agent_cli.cli import execute
from zebra_agent_config import ApiSettings, ModelSettings, ScmSettings, ZebraAgentSettings


def test_session_pull_request_contract_matrix_dry_run_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    idempotency_key = "pr-dry-run-1"

    api_response = build_app(
        database_path,
        settings=_settings(database_path),
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "body": "Implementation details.",
            "base_branch": "main",
            "head_branch": None,
            "dry_run": True,
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "pull-request",
            str(session_id),
            "--title",
            "Add feature",
            "--body",
            "Implementation details.",
            "--base-branch",
            "main",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert api_response.status_code == 200
    assert _normalize_api_pull_request(api_response.body) == _normalize_cli_pull_request(
        cli_result.payload
    )


def test_session_pull_request_contract_matrix_created_replays_from_cli_to_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZEBRA_SCM_NETWORK_PROFILE", "full-trusted-local")
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    idempotency_key = "pr-created-1"
    transport = _FakeGitHubTransport(url="https://github.example/pulls/1")

    def _create_cli_app(database: Path, *, settings: ZebraAgentSettings) -> object:
        return build_app(
            database,
            settings=settings,
            credential_env={"ZEBRA_TEST_MISSING_GITHUB_TOKEN": "cli-broker-token"},
            github_transport=transport,
        )

    monkeypatch.setattr(
        "zebra_agent_cli.session_pull_request_write.create_app",
        _create_cli_app,
    )

    cli_result = execute(
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
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path, scm=_github_scm(pull_request_dry_run=False)),
    )
    api_response = build_app(
        database_path,
        settings=_settings(database_path, scm=_github_scm(pull_request_dry_run=False)),
        credential_env={"ZEBRA_TEST_MISSING_GITHUB_TOKEN": "cli-broker-token"},
        github_transport=transport,
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Ship feature",
            "body": "",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
        idempotency_key=idempotency_key,
    )

    assert api_response.status_code == 200
    assert _normalize_cli_pull_request(cli_result.payload) == _normalize_api_pull_request(
        api_response.body
    )


def test_session_pull_request_contract_matrix_unavailable_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    idempotency_key = "pr-unavailable-1"

    api_response = build_app(
        database_path,
        settings=_settings(database_path),
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Try execute",
            "body": "",
            "base_branch": "main",
            "head_branch": None,
            "dry_run": False,
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "pull-request",
            str(session_id),
            "--title",
            "Try execute",
            "--execute",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert api_response.status_code == 409
    assert _normalize_api_pull_request(api_response.body) == _normalize_cli_pull_request(
        cli_result.payload
    )


def test_session_pull_request_contract_matrix_missing_session_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"
    idempotency_key = "pr-missing-1"

    api_response = build_app(
        database_path,
        settings=_settings(database_path),
    ).open_session_pull_request(
        session_id,
        {
            "title": "Missing session",
            "body": "",
            "base_branch": "main",
            "head_branch": None,
            "dry_run": True,
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "pull-request",
            session_id,
            "--title",
            "Missing session",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert api_response.status_code == 404
    assert _normalize_api_pull_request(api_response.body) == _normalize_cli_pull_request(
        cli_result.payload
    )


def test_session_pull_request_contract_matrix_policy_blocked_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="workspace_write")
    idempotency_key = "pr-policy-1"

    api_response = build_app(
        database_path,
        settings=_settings(database_path),
    ).open_session_pull_request(
        str(session_id),
        {
            "title": "Blocked PR",
            "body": "",
            "base_branch": "main",
            "head_branch": None,
            "dry_run": True,
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "pull-request",
            str(session_id),
            "--title",
            "Blocked PR",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert api_response.status_code == 409
    assert _normalize_api_pull_request(api_response.body) == _normalize_cli_pull_request(
        cli_result.payload
    )


def _normalize_api_pull_request(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_pull_request(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "database"
    }


def _seed_ready_session(
    database_path: Path,
    workspace_root: Path,
    *,
    policy_profile: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Pull request contract matrix",
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
