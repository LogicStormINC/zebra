from pathlib import Path
from subprocess import run

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_integrations import (
    GitHubPullRequestConfig,
    GitHubPullRequestGateway,
    GitHubPullRequestPayload,
)
from agent_storage import SQLiteDeliveryAuditStore, SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.session_pull_request import SessionPullRequestApi


def test_api_pull_request_response_and_audit_do_not_expose_github_token(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    gateway = GitHubPullRequestGateway(
        GitHubPullRequestConfig(
            owner="octo-org",
            repo="zebra-agent",
            token="secret-token",
            execution_enabled=True,
        ),
        transport=_FakeGitHubTransport(url="https://github.example/pulls/1"),
    )

    response = SessionPullRequestApi(
        database_path,
        pull_request_gateway=gateway,
    ).open_pull_request(
        str(session_id),
        {
            "title": "Add feature",
            "body": "Implementation details.",
            "base_branch": "main",
            "head_branch": "feature/zebra",
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    assert response.body["pull_request"]["status"] == "created"
    assert response.body["pull_request"]["url"] == "https://github.example/pulls/1"
    _assert_secret_absent("secret-token", response.body)
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "created"
    assert audit_records[0].result_metadata["provider"] == "github"
    assert audit_records[0].result_metadata["dry_run"] is False
    _assert_secret_absent("secret-token", audit_records[0].result_metadata)


def _seed_ready_session(
    database_path: Path,
    workspace_root: Path,
    *,
    policy_profile: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="SCM token redaction session",
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


class _FakeGitHubTransport:
    def __init__(self, *, url: str) -> None:
        self._url = url

    def create_pull_request(
        self,
        payload: GitHubPullRequestPayload,
        *,
        token: str,
    ) -> str:
        _ = payload
        _ = token
        return self._url


def _assert_secret_absent(secret: str, value: object) -> None:
    assert secret not in repr(value)
