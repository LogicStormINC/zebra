from pathlib import Path
from shutil import rmtree

from agent_runtime.workspace.errors import WorkspaceError, WorkspacePathError
from agent_runtime.workspace.models import LocalWorktree, WorkspaceLayout


def _normalize_root(path: str | Path) -> Path:
    root_path = Path(path).expanduser()
    if not root_path.is_absolute():
        raise WorkspacePathError("workspace root must be an absolute path")
    return root_path.resolve(strict=False)


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise WorkspaceError("worktree name must not be blank")
    if "/" in normalized or "\\" in normalized:
        raise WorkspaceError("worktree name must not contain path separators")
    if normalized in {".", ".."}:
        raise WorkspaceError("worktree name must not be a relative path marker")
    return normalized


class LocalWorkspace:
    def __init__(self, root_path: str | Path, *, worktree_root: str | Path | None = None) -> None:
        normalized_root = _normalize_root(root_path)
        normalized_worktree_root = (
            _normalize_root(worktree_root)
            if worktree_root is not None
            else normalized_root / ".agent" / "worktrees"
        )
        self._layout = WorkspaceLayout(
            root_path=normalized_root,
            worktree_root=normalized_worktree_root,
        )

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    def ensure(self) -> WorkspaceLayout:
        self._layout.root_path.mkdir(parents=True, exist_ok=True)
        self._layout.worktree_root.mkdir(parents=True, exist_ok=True)
        return self._layout

    def resolve_path(self, relative_path: str | Path) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise WorkspacePathError("workspace paths must be relative")

        resolved = (self._layout.root_path / candidate).resolve(strict=False)
        try:
            resolved.relative_to(self._layout.root_path)
        except ValueError as exc:
            raise WorkspacePathError("workspace path escapes the workspace root") from exc
        return resolved

    def create_worktree(self, name: str) -> LocalWorktree:
        normalized_name = _normalize_name(name)
        self.ensure()

        worktree_path = (self._layout.worktree_root / normalized_name).resolve(strict=False)
        try:
            worktree_path.relative_to(self._layout.worktree_root)
        except ValueError as exc:
            raise WorkspacePathError("worktree path escapes the worktree root") from exc

        worktree_path.mkdir(parents=True, exist_ok=False)
        return LocalWorktree(
            name=normalized_name,
            root_path=worktree_path,
            workspace_root=self._layout.root_path,
        )

    def destroy_worktree(self, worktree: LocalWorktree) -> None:
        try:
            worktree.root_path.relative_to(self._layout.worktree_root)
        except ValueError as exc:
            raise WorkspacePathError("worktree does not belong to this workspace") from exc

        if worktree.root_path.exists():
            rmtree(worktree.root_path)
