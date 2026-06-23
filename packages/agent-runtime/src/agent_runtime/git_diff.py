from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimePort

from agent_runtime.adapters.local import LocalRuntime


class WorkspaceDiffError(ValueError):
    """Raised when a workspace diff cannot be produced."""


@dataclass(frozen=True)
class WorkspaceDiffResult:
    workspace_root: Path
    git_status: str
    diff: str

    @property
    def clean(self) -> bool:
        return not self.git_status.strip()


class WorkspaceDiffService:
    def __init__(self, runtime: RuntimePort | None = None) -> None:
        self._runtime = runtime or LocalRuntime()

    def read_diff(self, workspace_root: Path) -> WorkspaceDiffResult:
        root = workspace_root.expanduser().resolve()
        if not root.exists():
            raise WorkspaceDiffError("workspace_root does not exist")
        if not root.is_dir():
            raise WorkspaceDiffError("workspace_root is not a directory")
        self._ensure_git_workspace(root)
        status = self._run_git(root, ("git", "status", "--short"))
        diff = self._run_git(root, ("git", "diff", "--no-ext-diff", "--"))
        return WorkspaceDiffResult(
            workspace_root=root,
            git_status=status,
            diff=diff,
        )

    def _ensure_git_workspace(self, workspace_root: Path) -> None:
        result = self._runtime.execute(
            RuntimeExecutionRequest(
                command=("git", "rev-parse", "--is-inside-work-tree"),
                cwd=str(workspace_root),
                timeout_seconds=5,
            )
        )
        if not result.succeeded or result.stdout.strip() != "true":
            raise WorkspaceDiffError("workspace_root is not a git repository")

    def _run_git(self, workspace_root: Path, command: tuple[str, ...]) -> str:
        result = self._runtime.execute(
            RuntimeExecutionRequest(
                command=command,
                cwd=str(workspace_root),
                timeout_seconds=10,
            )
        )
        if not result.succeeded:
            detail = result.stderr.strip() or "git command failed"
            raise WorkspaceDiffError(detail)
        return result.stdout
