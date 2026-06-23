from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.ports.runtime import RuntimeExecutionRequest, RuntimePort

from agent_runtime.adapters.local import LocalRuntime


class WorkspaceCommitError(ValueError):
    """Raised when a workspace commit cannot be created."""


@dataclass(frozen=True)
class WorkspaceCommitCommand:
    message: str
    author_name: str
    author_email: str

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("commit message must not be blank")
        if not self.author_name.strip():
            raise ValueError("commit author_name must not be blank")
        if not self.author_email.strip() or "@" not in self.author_email:
            raise ValueError("commit author_email must be a valid email")


@dataclass(frozen=True)
class WorkspaceCommitResult:
    workspace_root: Path
    commit_sha: str
    message: str


class WorkspaceCommitService:
    def __init__(self, runtime: RuntimePort | None = None) -> None:
        self._runtime = runtime or LocalRuntime()

    def commit(
        self, workspace_root: Path, command: WorkspaceCommitCommand
    ) -> WorkspaceCommitResult:
        root = workspace_root.expanduser().resolve()
        if not root.exists():
            raise WorkspaceCommitError("workspace_root does not exist")
        if not root.is_dir():
            raise WorkspaceCommitError("workspace_root is not a directory")
        self._ensure_git_workspace(root)
        if not self._has_changes(root):
            raise WorkspaceCommitError("workspace has no changes to commit")
        self._run_git(root, ("git", "add", "--all"))
        self._run_git(
            root,
            (
                "git",
                "-c",
                f"user.name={command.author_name.strip()}",
                "-c",
                f"user.email={command.author_email.strip()}",
                "commit",
                "-m",
                command.message.strip(),
                "--author",
                f"{command.author_name.strip()} <{command.author_email.strip()}>",
            ),
        )
        commit_sha = self._run_git(root, ("git", "rev-parse", "HEAD")).strip()
        return WorkspaceCommitResult(
            workspace_root=root,
            commit_sha=commit_sha,
            message=command.message.strip(),
        )

    def _ensure_git_workspace(self, workspace_root: Path) -> None:
        output = self._run_git(workspace_root, ("git", "rev-parse", "--is-inside-work-tree"))
        if output.strip() != "true":
            raise WorkspaceCommitError("workspace_root is not a git repository")

    def _has_changes(self, workspace_root: Path) -> bool:
        return bool(self._run_git(workspace_root, ("git", "status", "--short")).strip())

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
            raise WorkspaceCommitError(detail)
        return result.stdout
