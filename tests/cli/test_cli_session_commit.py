from pathlib import Path
from subprocess import run

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteDeliveryAuditStore, SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_commit_creates_local_commit(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "Commit session changes",
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "commit"
    assert result.payload["session_id"] == str(session_id)
    assert result.payload["database"] == str(database_path)
    assert result.payload["committed"] is True
    assert result.payload["message"] == "Commit session changes"
    assert result.payload["workspace"] == str(workspace)
    assert result.payload["policy_profile"] == "full_access"
    assert result.payload["idempotency_key"] is None
    assert len(str(result.payload["commit_sha"])) == 40
    assert _git(workspace, ("git", "status", "--short")) == ""
    assert len(SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)) == 1


def test_cli_commit_rejects_policy_blocked_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="workspace_write")

    result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "Try commit",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session_id),
        "status": "policy_blocked",
        "reason": "commit requires full_access session policy",
        "idempotency_key": None,
        "database": str(database_path),
    }


def test_cli_commit_rejects_clean_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "No changes",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session_id),
        "status": "commit_unavailable",
        "reason": "workspace has no changes to commit",
        "idempotency_key": None,
        "database": str(database_path),
    }


def test_cli_commit_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "commit",
            "00000000-0000-0000-0000-000000000001",
            "--message",
            "Commit",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
        "idempotency_key": None,
        "database": str(database_path),
    }


def test_cli_commit_replays_idempotent_response(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    argv = [
        "commit",
        str(session_id),
        "--message",
        "Commit once",
        "--idempotency-key",
        "commit-key-1",
        "--database",
        str(database_path),
    ]

    first_result = execute(argv)
    replayed_result = execute(argv)

    assert first_result.payload == replayed_result.payload
    assert replayed_result.payload["idempotency_key"] == "commit-key-1"
    assert len(SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)) == 1


def test_cli_commit_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "   ",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "status": "invalid_request",
        "reason": "message must be a non-blank string",
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
            title="Commit session",
            user_input="Commit reviewed changes.",
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
