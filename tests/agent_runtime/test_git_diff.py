from pathlib import Path
from subprocess import run

import pytest
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService


def test_workspace_diff_service_reports_clean_git_workspace(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")

    result = WorkspaceDiffService().read_diff(workspace)

    assert result.clean is True
    assert result.git_status == ""
    assert result.diff == ""


def test_workspace_diff_service_reports_dirty_git_workspace(tmp_path: Path) -> None:
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")

    result = WorkspaceDiffService().read_diff(workspace)

    assert result.clean is False
    assert result.git_status == " M tracked.txt\n"
    assert "+changed" in result.diff


def test_workspace_diff_service_rejects_non_git_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(WorkspaceDiffError, match="not a git repository"):
        WorkspaceDiffService().read_diff(workspace)


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
    return path
