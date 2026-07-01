from pathlib import Path
from subprocess import run

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_diff_reports_dirty_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace)

    result = execute(["diff", str(session_id), "--database", str(database_path)])

    assert result.command == "diff"
    assert result.payload["session_id"] == str(session_id)
    assert result.payload["database"] == str(database_path)
    assert result.payload["status"] == "ok"
    assert result.payload["workspace"] == str(workspace)
    assert result.payload["clean"] is False
    assert result.payload["git_status"] == " M tracked.txt\n"
    assert "+changed" in str(result.payload["diff"])


def test_cli_diff_reports_clean_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace)

    result = execute(["diff", str(session_id), "--database", str(database_path)])

    assert result.payload == {
        "session_id": str(session_id),
        "database": str(database_path),
        "status": "ok",
        "workspace": str(workspace),
        "clean": True,
        "git_status": "",
        "diff": "",
    }


def test_cli_diff_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "diff",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }


def test_cli_diff_rejects_non_git_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "not-git"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)

    result = execute(["diff", str(session_id), "--database", str(database_path)])

    assert result.payload == {
        "session_id": str(session_id),
        "database": str(database_path),
        "status": "diff_unavailable",
        "reason": "workspace_root is not a git repository",
    }


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Diff session",
            user_input="Review the diff.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _git_workspace(path: Path) -> Path:
    path.mkdir()
    run(("git", "init"), cwd=path, check=True, capture_output=True, text=True)
    run(
        ("git", "config", "user.name", "Zebra Agent"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    run(
        ("git", "config", "user.email", "zebra@example.com"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    run(("git", "add", "tracked.txt"), cwd=path, check=True, capture_output=True, text=True)
    run(("git", "commit", "-m", "init"), cwd=path, check=True, capture_output=True, text=True)
    return path.resolve()
