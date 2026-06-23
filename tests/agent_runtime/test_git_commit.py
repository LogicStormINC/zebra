from pathlib import Path
from subprocess import run

import pytest
from agent_runtime import WorkspaceCommitCommand, WorkspaceCommitError, WorkspaceCommitService


def test_workspace_commit_service_commits_dirty_workspace(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")

    result = WorkspaceCommitService().commit(
        workspace,
        WorkspaceCommitCommand(
            message="Update tracked file",
            author_name="Zebra Agent",
            author_email="zebra@example.com",
        ),
    )

    assert len(result.commit_sha) == 40
    assert result.message == "Update tracked file"
    assert _git(workspace, ("git", "status", "--short")) == ""


def test_workspace_commit_service_rejects_clean_workspace(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")

    with pytest.raises(WorkspaceCommitError, match="no changes"):
        WorkspaceCommitService().commit(
            workspace,
            WorkspaceCommitCommand(
                message="No changes",
                author_name="Zebra Agent",
                author_email="zebra@example.com",
            ),
        )


def test_workspace_commit_command_rejects_invalid_author_email() -> None:
    with pytest.raises(ValueError, match="valid email"):
        WorkspaceCommitCommand(
            message="Update",
            author_name="Zebra Agent",
            author_email="invalid",
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
