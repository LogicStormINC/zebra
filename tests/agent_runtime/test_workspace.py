from pathlib import Path

import pytest
from agent_runtime.workspace import LocalWorkspace, WorkspaceError, WorkspacePathError


def test_local_workspace_rejects_non_absolute_root() -> None:
    with pytest.raises(WorkspacePathError, match="absolute path"):
        LocalWorkspace("relative-root")


def test_local_workspace_resolves_paths_within_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)

    resolved = workspace.resolve_path("src/module.py")

    assert resolved == tmp_path / "src" / "module.py"


def test_local_workspace_rejects_escape_paths(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)

    with pytest.raises(WorkspacePathError, match="escapes the workspace root"):
        workspace.resolve_path("../outside.txt")


def test_local_workspace_creates_and_destroys_worktree(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)

    worktree = workspace.create_worktree("sess-001")

    assert worktree.name == "sess-001"
    assert worktree.workspace_root == tmp_path
    assert worktree.root_path == tmp_path / ".agent" / "worktrees" / "sess-001"
    assert worktree.root_path.is_dir()

    workspace.destroy_worktree(worktree)

    assert not worktree.root_path.exists()


def test_local_workspace_rejects_invalid_worktree_name(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)

    with pytest.raises(WorkspaceError, match="path separators"):
        workspace.create_worktree("nested/name")
