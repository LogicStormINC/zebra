"""Runtime package for Zebra Agent."""

from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeHandle,
    RuntimeSnapshot,
)

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.git_commit import (
    WorkspaceCommitCommand,
    WorkspaceCommitError,
    WorkspaceCommitResult,
    WorkspaceCommitService,
)
from agent_runtime.git_diff import WorkspaceDiffError, WorkspaceDiffResult, WorkspaceDiffService
from agent_runtime.harness import LocalToolGateway, run_local_harness
from agent_runtime.research import (
    LocalResearchSubagentRunner,
    ReadOnlyToolGateway,
    ResearchSubagentTool,
)
from agent_runtime.subagents import (
    LocalResearchSubagentCoordinator,
    SubagentLimitError,
    UnknownSubagentError,
)
from agent_runtime.workspace import (
    LocalWorkspace,
    LocalWorktree,
    WorkspaceError,
    WorkspaceLayout,
    WorkspacePathError,
)

__all__ = [
    "LocalRuntime",
    "LocalResearchSubagentCoordinator",
    "LocalResearchSubagentRunner",
    "LocalToolGateway",
    "LocalWorkspace",
    "LocalWorktree",
    "ReadOnlyToolGateway",
    "ResearchSubagentTool",
    "RuntimeCapabilityError",
    "RuntimeHandle",
    "RuntimeSnapshot",
    "SubagentLimitError",
    "UnknownSubagentError",
    "WorkspaceCommitCommand",
    "WorkspaceCommitError",
    "WorkspaceCommitResult",
    "WorkspaceCommitService",
    "WorkspaceDiffError",
    "WorkspaceDiffResult",
    "WorkspaceDiffService",
    "WorkspaceError",
    "WorkspaceLayout",
    "WorkspacePathError",
    "run_local_harness",
]
