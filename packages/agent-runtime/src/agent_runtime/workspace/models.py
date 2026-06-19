from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceLayout:
    root_path: Path
    worktree_root: Path


@dataclass(frozen=True)
class LocalWorktree:
    name: str
    root_path: Path
    workspace_root: Path
